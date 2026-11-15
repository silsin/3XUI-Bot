# Campaign Moderation Investigation

## Summary

The "campaign" feature in this codebase is called **offers (تخفیف‌ها)**. The admin panel
menu entry "🏷 تخفیف‌ها و پیشنهادها" leads to a fully-wired handler and service layer.
All four moderation actions exist in some form, but **three are broken or missing** due to
a single critical bug plus two missing features:

| Action | Status | Root cause |
|--------|--------|-----------|
| **Disable / Enable** (toggle) | ✅ Handler wired, button exists | — works in principle, but **the button is never rendered** (see Bug #1) |
| **Remove / Delete** | ✅ Handler wired, button exists | Same — **button never rendered** (Bug #1) |
| **Edit** | ❌ Completely absent | No handler, no button, no service call |
| **Renew / Extend validity** | ❌ Completely absent | No handler, no button, no service call |

The root cause for disable and remove is **Bug #1**: `offer_detail_kb()` in
`app/keyboards/admin.py` builds the keyboard but **never returns it** — it falls off the
end of the function and returns `None`. Every call site that passes this keyboard to
`edit_text(..., reply_markup=kb.offer_detail_kb(offer))` silently passes `None` as the
markup, so the message is rendered with no buttons at all.

---

## Evidence

### Bug #1 — `offer_detail_kb` returns `None`

**File:** `app/keyboards/admin.py`, lines 258–272

```python
def offer_detail_kb(offer) -> InlineKeyboardMarkup:
    """دکمه‌های مدیریت یک تخفیف."""
    b = InlineKeyboardBuilder()
    toggle_label = "⚪️ غیرفعال‌سازی" if offer.is_active else "🟢 فعال‌سازی"
    b.button(
        text=toggle_label,
        callback_data=AdminCB(action="offer_toggle", arg=offer.id),
    )
    b.button(
        text="🗑 حذف تخفیف",
        callback_data=AdminCB(action="offer_del_confirm", arg=offer.id),
    )
    b.adjust(2)
    b.row(_back("offers"))
    # ← NO return statement here!
```

The function ends at line 272 without `return b.as_markup()`. Every other keyboard
function in the same file (e.g. `offers_list_kb`, `confirm`, `package_view`) correctly
ends with `return b.as_markup()`. This one was left incomplete.

**Call sites affected** (all pass `None` as `reply_markup`):

- `app/handlers/admin/offers.py` line 119 — `offer_view` handler
- `app/handlers/admin/offers.py` line 138 — `offer_toggle` handler  
- `app/handlers/admin/offers.py` line 370 — `offer_step_valid_days` (after creation)

**Effect:** When an admin opens an offer, the detail message is shown but has zero
buttons — no toggle, no delete, no back. The admin is stuck and cannot perform any
moderation action.

---

### Bug #2 — No "Edit" action for offers

**Missing from:** `app/keyboards/admin.py` (`offer_detail_kb`), `app/handlers/admin/offers.py`, `app/states.py`

No button, no callback handler, no FSM state, and no service function exists for editing
any field of an existing offer. Comparable features (packages, panels, settings) all have
an edit flow: a list of editable fields is shown (`pkg_edit` / `panel_edit_field`), the
admin picks one, enters a new value in a message, and the field is saved. None of that
exists for offers.

Fields a user would want to edit: title, code, value, max_uses, per_user, valid_until,
is_active (this one is handled by toggle once Bug #1 is fixed).

**Services layer:** `app/services/offers_service.py` has `create_offer` and
`delete_offer` but no `update_offer` function.

---

### Bug #3 — No "Renew / Extend validity" action for offers

**Missing from:** `app/keyboards/admin.py` (`offer_detail_kb`), `app/handlers/admin/offers.py`, `app/states.py`, `app/services/offers_service.py`

A common need is to extend the expiry date of an offer that has a `valid_until` set.
There is no button, no handler, and no service function for this. The only way to
accomplish it today is to delete the offer and re-create it — but re-creation resets
`used_count` to zero, losing usage history.

A "renew" action would prompt the admin for a number of additional days, then set
`valid_until = max(now, valid_until) + timedelta(days=N)`.

---

### Permission guard — works correctly, not the cause

**File:** `app/filters.py`

```python
class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        return user is not None and get_settings().is_admin(user.id)
```

The offers router applies this filter at the router level
(`app/handlers/admin/offers.py` lines 20–21):

```python
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())
```

The filter is straightforward. It checks `ADMIN_IDS` from config. No role-based
sub-permission system exists; any admin ID can reach all offer actions. Permission is
**not** the cause of the moderation block.

---

### Router registration — correct, not the cause

**File:** `app/handlers/admin/__init__.py`

```python
def get_admin_router() -> Router:
    router = Router(name="admin")
    ...
    router.include_router(offers.router)   # ← registered
    ...
```

The offers router is correctly included in the admin router, which is correctly included
as the first router in the root (`app/handlers/__init__.py`). Router registration is
**not** the cause.

---

### Existing handlers that do work (once buttons are visible)

**File:** `app/handlers/admin/offers.py`

| Handler | Callback action | Status |
|---------|----------------|--------|
| `offers_list` | `offers` | ✅ works |
| `offer_view` | `offer_view` | ✅ works (displays detail) |
| `offer_toggle` | `offer_toggle` | ✅ wired — but unreachable due to Bug #1 |
| `offer_del_confirm` | `offer_del_confirm` | ✅ wired — but unreachable due to Bug #1 |
| `offer_del_do` | `offer_del_do` | ✅ wired — but unreachable due to Bug #1 |
| `offer_add_start` + steps | `offer_add` | ✅ works (7-step FSM flow) |

---

## Conclusions

The admin **can** list offers and **can** create new ones. Everything else is blocked by a
missing `return` statement in one keyboard function. That single line fix restores
toggle and delete immediately.

Edit and renew require new code.

---

## Recommended Fixes

### Fix 1 — Add missing `return` to `offer_detail_kb` (1 line, unblocks toggle + delete)

**File:** `app/keyboards/admin.py`, after line 271 (`b.row(_back("offers"))`):

```python
    b.row(_back("offers"))
    return b.as_markup()          # ← ADD THIS LINE
```

### Fix 2 — Add "Edit offer" flow

**Files to change:**

1. `app/keyboards/admin.py` — add an "✏️ ویرایش" button to `offer_detail_kb` with
   `callback_data=AdminCB(action="offer_edit", arg=offer.id)`, and add a new
   `offer_edit_fields_kb(offer)` function listing editable fields (title, code, value,
   max_uses, per_user, valid_until).

2. `app/states.py` — add states for the edit flow:
   ```python
   offer_edit_field = State()     # waiting for new field value
   ```

3. `app/handlers/admin/offers.py` — add handlers:
   - `offer_edit`: shows editable fields keyboard
   - `offer_edit_field`: receives `field` name, asks for new value
   - `offer_edit_value`: receives new value, validates, calls service

4. `app/services/offers_service.py` — add:
   ```python
   async def update_offer(session, offer_id, **fields) -> Offer | None: ...
   ```

### Fix 3 — Add "Renew / Extend validity" action

**Files to change:**

1. `app/keyboards/admin.py` — add "🔄 تمدید اعتبار" button to `offer_detail_kb` with
   `callback_data=AdminCB(action="offer_extend", arg=offer.id)`.

2. `app/states.py` — add:
   ```python
   offer_extend_days = State()
   ```

3. `app/handlers/admin/offers.py` — add handlers:
   - `offer_extend`: prompts admin for number of days
   - `offer_extend_days`: receives days, updates `valid_until` via service

4. `app/services/offers_service.py` — add:
   ```python
   async def extend_offer(session, offer_id, days: int) -> Offer | None:
       offer = await session.get(Offer, offer_id)
       if offer is None:
           return None
       now = datetime.now(timezone.utc)
       base = max(now, offer.valid_until) if offer.valid_until else now
       offer.valid_until = base + timedelta(days=days)
       if offer.valid_from is None:
           offer.valid_from = now
       await session.commit()
       return offer
   ```

---

## File Reference Summary

| File | Relevant lines | Issue |
|------|---------------|-------|
| `app/keyboards/admin.py` | 258–272 (`offer_detail_kb`) | Missing `return b.as_markup()` |
| `app/handlers/admin/offers.py` | entire file | Toggle/delete wired but unreachable; edit/renew absent |
| `app/services/offers_service.py` | entire file | `update_offer` and `extend_offer` missing |
| `app/states.py` | 22–28 (offer states) | No edit/extend states |
| `app/filters.py` | whole file | Correct — not the cause |
| `app/handlers/admin/__init__.py` | 15 | Router registered — not the cause |
