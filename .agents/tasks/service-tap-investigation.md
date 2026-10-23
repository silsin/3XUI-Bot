# Investigation: Tapping a Purchased Service Does Nothing

**File:** `d:\alovpnBot\.agents\tasks\service-tap-investigation.md`  
**Date:** Investigation completed  
**Status:** Root causes identified — two distinct failure modes found

---

## Summary Answer

There are **two bugs** that together explain why tapping a service silently does nothing:

1. **Primary bug — `sync_service` fails silently and `edit_text` is swallowed.**  
   `view_service` (services.py:163) calls `provisioning.sync_service(...)` which makes a live HTTP call to the VPN panel. If the panel is unreachable or returns an error, `sync_service` raises an exception. That exception is **not caught** inside `view_service` before `call.answer()` is called, so `call.answer()` is never reached either — Telegram's loading spinner keeps spinning forever and the user sees nothing. Even if `sync_service` succeeds, the subsequent `call.message.edit_text(...)` is wrapped in `except Exception: pass`, meaning any error (e.g. a Telegram "message not modified" error, a DB lazy-load MappedInstanceError, or a rendering exception) is silently discarded.

2. **Secondary bug — services migrated from the old server have no `ServiceClient` rows.**  
   The user reports moving to a new server. The original bot created `Service` records that each had a single `config_link` field stored directly on the `Service` table (the legacy path). The `ServiceClient` table (one row per protocol per service) is populated only for services created *after* the multi-inbound feature was added. When `service.clients` is empty and `service.config_link` is also empty (possible after a DB restore without config links), `_detail_text` still succeeds but `service_detail_kb` renders **no config buttons** — so even when the handler runs correctly, the user has nothing to tap for configs.

---

## Evidence

### Q1 — What callback_data is sent when the user taps a service?

**File:** `app/keyboards/inline.py`, function `services_kb` (line ~258)

```python
builder.button(
    text=f"{mark} {item.title} ({days_left_text(item.expires_at)})",
    callback_data=ServiceCB(action="view", service_id=item.id),
)
```

Callback data is `ServiceCB(action="view", service_id=<int>)`, packed as `srv:view:<service_id>:0` (prefix `srv`, fields in declaration order: `action`, `service_id=0`, `client_id=0`).

---

### Q2 — Is there a handler registered for that callback?

**Yes.** `app/handlers/services.py`, line 157:

```python
@router.callback_query(inline.ServiceCB.filter(F.action == "view"))
async def view_service(...)
```

The `services.router` is included in the root router at `app/handlers/__init__.py` (line 14, `root.include_router(services.router)`). Router registration is correct.

---

### Q3 — What causes the handler to silently do nothing?

#### Bug A: `sync_service` raises, kills the handler before `call.answer()`

`view_service` (services.py:163–182):

```python
async def view_service(call, callback_data, session, user):
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return
    # ← HERE: live HTTP to VPN panel, no try/except
    service = await provisioning.sync_service(session, service)
    await call.answer()          # ← never reached if sync_service raises
    try:
        await call.message.edit_text(...)
    except Exception:            # ← swallows ALL errors silently
        pass
```

`sync_service` (provisioning.py:574) calls `_usage_for` → `provider.get_all_usage()` — a network call to the VPN panel. If the panel is down, credentials changed after the server migration, or any network error occurs, this raises an exception that propagates back through `view_service` **without being caught**. The result:
- `call.answer()` is never called → Telegram shows the loading indicator indefinitely.
- No error message is sent to the user.
- No log entry at ERROR level (the exception bubbles up to aiogram's middleware, which may log it at WARNING or silently drop it depending on configuration).

This is the **most likely cause** given the user just migrated to a new server — panel credentials or URL may not be correctly configured.

#### Bug B: `except Exception: pass` swallows `edit_text` errors

Even when `sync_service` succeeds, the `edit_text` call is inside:

```python
try:
    await call.message.edit_text(...)
except Exception:  # noqa: BLE001 — پیام تغییری نکرده
    pass
```

This was intended to suppress Telegram's "message is not modified" error (which is harmless). But it also suppresses:
- `MappedInstanceError` from SQLAlchemy async lazy-loading (if `service.clients` is not loaded)
- Any exception from `_detail_text` or `service_detail_kb`
- Telegram `TelegramBadRequest` for any reason

So if `sync_service` succeeds but `_detail_text` fails for any reason, the user still sees nothing.

---

### Q4 — Missing router registrations, unhandled exceptions, filter mismatches?

- **Router registration:** Correct. `services.router` is in `get_root_router()` (handlers/__init__.py:14).
- **ChannelMembershipMiddleware:** Could block the callback entirely if the required-channel feature is enabled and the bot lost admin status on the channel after the server migration. In that case, `get_chat_member` raises, `is_member` defaults to `False`, and the middleware returns `None` (line ~108 in middlewares.py), never calling the handler. The user would see a "join channel" message instead of nothing — but if `show_channel_membership_required` also fails (e.g. `create_chat_invite_link` fails), the middleware swallows the exception and still returns `None` with no user-visible response.
- **Filter match:** `ServiceCB.filter(F.action == "view")` is a standard `CallbackData` filter. No mismatch.
- **`callback_data` parameter injection:** `view_service` declares `callback_data: inline.ServiceCB`. aiogram 3 injects this automatically when using `CallbackData.filter()`. This is correct.

---

### Q5 — ServiceClient relationship loading

`sync_service` (provisioning.py:574) calls `_load_service` first (line 574):

```python
service = await _load_service(session, service.id) or service
```

`_load_service` (provisioning.py:113) uses `selectinload(Service.clients)`, so after `sync_service` returns, `service.clients` is properly populated. This is **not** the source of a lazy-load error in the happy path.

However, the user's migrated services almost certainly have **zero `ServiceClient` rows** in the new database. The legacy code stored the config in `Service.config_link` directly. Looking at `_detail_text` (services.py:80):

```python
clients = sorted(service.clients, key=lambda c: c.id)
if clients:
    lines.append("🔐 برای دریافت کانفیگ ...")
elif service.config_link:
    lines.append(f"\n🔐 کانفیگ:\n<code>{service.config_link}</code>")
```

And `service_detail_kb` (inline.py:~200):

```python
clients = sorted(
    [c for c in getattr(service, "clients", []) if c.enabled],
    key=lambda c: c.id
)
cfg_rows: list[int] = []
if clients:
    for c in clients:
        builder.button(text=f"📥 {label}", ...)
```

If `service.clients` is empty **and** `service.config_link` is empty or was never populated, the detail page renders with no config buttons. The user sees the service info but has no way to get a config. This matches the description exactly: tapping the service "does nothing useful."

---

## Conclusions

| # | Root Cause | Severity | Where |
|---|-----------|----------|-------|
| 1 | `sync_service` makes a live panel call without try/except in `view_service`; if panel is unreachable, the handler crashes before `call.answer()`, giving the user a spinning loader forever | **Critical** | `app/handlers/services.py:169` |
| 2 | `except Exception: pass` around `edit_text` silently swallows all rendering/edit errors | **High** | `app/handlers/services.py:173–177` |
| 3 | Migrated services have no `ServiceClient` rows — the bot was migrated but the old `bot.db` with client records was not restored, OR services predate the multi-inbound feature | **High** | DB state / migration |
| 4 | `ChannelMembershipMiddleware` can silently block callbacks if panel migration also changed the bot's channel admin status | **Medium** | `app/middlewares.py:108` |

---

## Recommendations (do not implement — investigation only)

### Fix 1 — Wrap `sync_service` in try/except in `view_service`

```python
@router.callback_query(inline.ServiceCB.filter(F.action == "view"))
async def view_service(call, callback_data, session, user):
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return
    try:
        service = await provisioning.sync_service(session, service)
    except Exception:
        logger.exception("sync_service failed for service %s", callback_data.service_id)
        # still load clients so we can show the detail page without fresh usage
        service = await session._get_service_with_clients(...)  # or re-fetch
    await call.answer()
    # ... rest of handler
```

Minimally: move `await call.answer()` to **before** `sync_service`, so at minimum the spinner clears even if the panel is down.

### Fix 2 — Replace `except Exception: pass` with a logged error or fallback

```python
try:
    await call.message.edit_text(...)
except TelegramBadRequest as e:
    if "message is not modified" not in str(e):
        logger.warning("edit_text failed: %s", e)
except Exception:
    logger.exception("unexpected edit_text failure")
    await call.answer("خطایی رخ داد. دوباره تلاش کنید.", show_alert=True)
```

### Fix 3 — Run "Rebuild Configs" (`regen_config`) for all migrated services

The admin panel has a "بازسازی کانفیگ" button that calls `provisioning.regenerate_links`. Running this for all services will create `ServiceClient` rows and populate `config_link` values from the VPN panel. This is the correct recovery path for migrated services without config data.

**Steps:**
1. Ensure the VPN panel URL and credentials in `.env` are correct on the new server.
2. Open the bot as admin → find each user's service → tap "🔁 بازسازی کانفیگ".
3. Alternatively, add an admin command to run `regenerate_links(session)` (no `service_id`) for all services in bulk.

### Fix 4 — Verify panel credentials after migration

The most immediate step: check `.env` on the new server for `XUI_BASE_URL`, `XUI_USERNAME`, `XUI_PASSWORD` (or `XUI_API_TOKEN` for xui3 variant). These values must point to the VPN panel running on the new or original server. If the panel is still on the old server, the bot must keep pointing there until the panel itself is also migrated.

### Fix 5 — Check `ChannelMembershipMiddleware` bot admin status

If `REQUIRED_CHANNEL_ENABLED=true` in settings, verify the bot still has admin rights in the required channel. If not, either grant admin rights or disable the requirement temporarily while debugging.
