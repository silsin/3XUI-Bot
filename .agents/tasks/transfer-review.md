# Telegram-triggered bot transfer to a new server

This feature adds a nine-step transfer pipeline triggered entirely from within Telegram: an admin sends SSH credentials in a message, confirms on a keyboard, and the bot copies its code, database, and `.env` to a destination server via asyncssh, then starts the bot there with `docker compose up --build`. After a successful transfer the admin can optionally shut down the source. The credentials message is deleted immediately, FSM state is cleared before the background task runs, and sensitive details are never forwarded to Telegram in error messages. Three FSM states are added to `AdminFlow`; they don't collide with existing states. The router is appended at the end of `get_admin_router()`.

Watch for: (1) **confirmed** — `transfer_confirm_yes` has no FSM state filter, so the callback fires from any state; a stale confirm button from a prior session can launch a transfer; (2) **confirmed** — the `docker compose ps` status check compares the first output line against `"running"`, which fails silently on multi-service stacks or Compose versions that emit empty leading lines; (3) **confirmed** — the `.env` copy uses `cat SOURCE_DIR/.env` inside the source process space; the admin gets no progress message confirming which file was sent, making it hard to detect a misconfigured path before `docker compose up` runs on the destination.

**Verdict**: NEEDS_CHANGES

---

## High-level view

The FSM flow — collect credentials → confirm → background transfer — is structurally sound and the credential hygiene (immediate message delete, state clear before task launch, no secrets in Telegram error text) is well done. The weak point is the `transfer_confirm_yes` callback: it checks for credentials in FSM data but carries no state guard, so a leftover "yes" button from a previous session can trigger a transfer attempt with stale or absent creds. The FSM guard was applied to `transfer_disable_yes` and `transfer_disable_no` but not to the earlier confirm handler.

The transfer logic runs `docker compose ps --format '{{.State}}' | head -1` to detect container liveness. Docker Compose v2 wraps each service's state in its own line; `head -1` picks the first, which may be an empty string or a header depending on the compose version. Stacks with multiple services (e.g. bot + nginx) are also silently mishandled. A `docker compose ps --quiet` or `docker compose ps | grep -c "Up"` check would be more robust.

The `.env` copy reads the file via `cat SOURCE_DIR/.env` using `asyncio.create_subprocess_exec`. Inside a Docker container `SOURCE_DIR` (`/opt/alovpnBot`) is the container mount, so the `.env` at that path is the one the container sees — this likely works in practice. However if the bot is running with a volume-mounted `.env` that differs from the image's path, the copy silently sends the wrong file and `docker compose up` on the destination starts with incorrect config. The admin receives no indication of which `.env` path was used.

The `known_hosts=None` posture is disclosed to the admin on the confirmation screen with a MITM warning — deliberate trade-off, no action needed.

---

<details>
<summary>Issues (3)</summary>

1. **Missing FSM guard on `transfer_confirm_yes`** — The callback fires from any state, including none. A stale confirm button in an old message can start a transfer attempt with absent credentials. Add `AdminFlow.transfer_confirm` as a state filter on the decorator, the same way `transfer_disable_yes` is guarded with `AdminFlow.transfer_done`.

2. **Container status check fragility** — `docker compose ps --format '{{.State}}' | head -1` returns `"running"` only on single-service stacks with Docker Compose v2; empty lines, header rows, or multi-service output make the check fail silently, causing a 120-second timeout on what would otherwise be a healthy deployment. Replace with `docker compose ps --quiet | wc -l` (returns > 0 when any service is up) or check for `"Up"` in plain `docker compose ps` output.

3. **`.env` source path assumption** — `cat /opt/alovpnBot/.env` is run with `asyncio.create_subprocess_exec` inside the source server's process space. If the bot runs in a Docker container with a volume-mounted `.env`, the file at that path may not match the actually-running config. The admin gets no feedback about which path was read. Log the resolved path to the Telegram progress message so the admin can confirm it's the right file.

</details>

---

<details>
<summary>Details</summary>

### Missing FSM guard on `transfer_confirm_yes`

The two shutdown callbacks are correctly guarded:

```python
@router.callback_query(
    kb.AdminCB.filter(F.action == "transfer_disable_yes"),
    AdminFlow.transfer_done,   # ← state filter present
)
```

The confirm callback is not:

```python
@router.callback_query(kb.AdminCB.filter(F.action == "transfer_confirm_yes"))
async def transfer_confirm_yes(call: CallbackQuery, state: FSMContext) -> None:
```

If the admin sends credentials, sees the confirm screen, navigates away without pressing anything, and later taps the old "yes" button, `state.get_data()` returns `{}`, `creds` is `None`, the handler calls `call.answer` with an alert and clears state — so the worst-case outcome is a noisy alert rather than a runaway transfer. The risk is low, but the inconsistency is a latent bug: if state happened to contain creds from a different flow's key named `creds`, the transfer would fire. Adding `AdminFlow.transfer_confirm` to the decorator brings it in line with the rest of the flow and eliminates the ambiguity at zero cost.

### Container readiness check fragility

```python
r_status = await conn.run(
    f"cd {dest_dir} && docker compose ps --format '{{{{.State}}}}' | head -1",
    check=False,
)
status = (r_status.stdout or "").strip()
if status == "running":
    container_up = True
    break
```

With Docker Compose v2 on a single-service stack this usually works. On a multi-service stack the first line returned by `head -1` is the state of whatever service sorts first — it could be `"exited"` if a dependency container stopped cleanly. More critically, some Compose versions emit an empty first line. The loop then runs all 24 iterations (2 minutes) even though the container started at iteration 2.

A safer one-liner: `docker compose ps --quiet | grep -c .` returns the count of running service containers (non-zero means at least one is up). The existing `head -1 | grep running` pattern can be replaced with that.

### `.env` path and the Docker container boundary

The bot reads its own `.env` with:

```python
env_proc = await asyncio.create_subprocess_exec(
    "cat", f"{SOURCE_DIR}/.env", ...
)
```

The file at `SOURCE_DIR/.env` is the one the running container sees when the project root is volume-mounted — the common case. If `.env` is injected by a different mechanism (Docker secrets, a compose `env_file` pointing elsewhere), the file either doesn't exist or is stale at that path. The handler raises `RuntimeError` on a missing or empty file, so the transfer halts cleanly when the file is absent. What's missing is a progress message that shows the resolved path, so the admin can confirm the right file was sent before `docker compose up` runs on the destination.


</details>

---

<details>
<summary>File map</summary>

| File | Change |
|---|---|
| `app/handlers/admin/transfer.py` | New file — full transfer pipeline (559 lines) |
| `app/states.py` | Added `transfer_creds`, `transfer_confirm`, `transfer_done` to `AdminFlow` |
| `app/keyboards/admin.py` | Added `transfer` button to `home()`, new `transfer_confirm_kb()` and `transfer_disable_kb()` |
| `app/handlers/admin/__init__.py` | Imported and registered `transfer.router` |
| `requirements.txt` | Added `asyncssh==2.18.0` |

Full diff: `git diff e3e0c4b HEAD -- app/handlers/admin/transfer.py app/states.py app/keyboards/admin.py app/handlers/admin/__init__.py requirements.txt`

</details>
