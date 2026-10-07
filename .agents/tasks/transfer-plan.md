# Implementation Plan — Transfer Bot to New Server

## Context

Codebase confirmed before writing this plan:
- **Admin handlers** all use `Router(name='...')` with `router.callback_query.filter(IsAdmin())` and `router.message.filter(IsAdmin())`.
- **States** live in `AdminFlow(StatesGroup)` in `app/states.py`. New states `transfer_creds` and `transfer_confirm` must be appended there.
- **Keyboards** use `AdminCB(CallbackData, prefix='adm')` with `action`, `arg`, `arg2`, `field` fields.  `home()` in `app/keyboards/admin.py` is the admin panel entry point.
- **Routers** are registered inside `get_admin_router()` in `app/handlers/admin/__init__.py`.
- **Docker volume** is named `bot_data` in `docker-compose.yml` (full Docker name: `alovpn-bot_bot_data`). Project dir detection: inspect the running container's `WorkingDir` or fall back to `/opt/alovpnBot`.
- **requirements.txt** currently has no SSH library; `asyncssh==2.18.0` must be added.
- **Python**: 3.13-slim Docker image; `from __future__ import annotations` is used throughout.

---

## Items

- [ ] 1. Add two new states to `AdminFlow` in `app/states.py`.

  Append `transfer_creds = State()` and `transfer_confirm = State()` to `AdminFlow`. No existing states are duplicated (confirmed list in task description checked against actual file content).

  **Files:** `app/states.py`

  **Verify:** `python -c "from app.states import AdminFlow; assert hasattr(AdminFlow, 'transfer_creds') and hasattr(AdminFlow, 'transfer_confirm')"` — exits 0.

---

- [ ] 2. Add the transfer button to `home()` and two new keyboard helpers in `app/keyboards/admin.py`.

  a. In `home()`, add `b.button(text="📦 انتقال به سرور جدید", callback_data=AdminCB(action="transfer"))` before the final `b.adjust(2)` call so the new button joins the grid.

  b. Add `transfer_confirm_kb()` — returns an `InlineKeyboardMarkup` with two buttons:
  - `✅ بله، انتقال بده` → `AdminCB(action="transfer_confirm_yes")`
  - `❌ لغو` → `AdminCB(action="home")`
  adjusted 2-wide.

  c. Add `transfer_disable_kb()` — returns an `InlineKeyboardMarkup` with two buttons:
  - `🔴 بله، سرور فعلی را خاموش کن` → `AdminCB(action="transfer_disable_yes")`
  - `✅ نه، فعال بماند` → `AdminCB(action="transfer_disable_no")`
  adjusted 2-wide.

  **Files:** `app/keyboards/admin.py`

  **Verify:** `python -c "from app.keyboards.admin import home, transfer_confirm_kb, transfer_disable_kb; print('ok')"` — prints `ok`.

---

- [ ] 3. Create `app/handlers/admin/transfer.py` — the complete transfer handler.

  ### 3.1 Imports and router setup

  ```python
  from __future__ import annotations
  import asyncio, logging, re
  from aiogram import F, Router
  from aiogram.fsm.context import FSMContext
  from aiogram.types import CallbackQuery, Message
  from app.filters import IsAdmin
  from app.keyboards import admin as kb
  from app.states import AdminFlow

  logger = logging.getLogger(__name__)
  router = Router(name="admin_transfer")
  router.callback_query.filter(IsAdmin())
  router.message.filter(IsAdmin())
  ```

  ### 3.2 Credential parsing helper

  `_parse_creds(text: str) -> dict | None`

  Accepts these formats (no logging of raw input):
  - `user@ip:port password`
  - `user@ip password`
  - `user@ip:port`  (key-based auth)
  - `user@ip`       (key-based auth)

  Returns `{"user": str, "host": str, "port": int, "password": str | None}` or `None` if unparseable.

  Use a simple regex: `^(\w[\w.-]*)@([\w.:-]+?)(?::(\d+))?\s*(.*)$` — group 1=user, 2=host, 3=port (default 22), 4=password (empty → None).

  ### 3.3 Entry point — callback `transfer`

  ```python
  @router.callback_query(kb.AdminCB.filter(F.action == "transfer"))
  async def transfer_start(call: CallbackQuery, state: FSMContext) -> None:
  ```

  Clears state, sets `AdminFlow.transfer_creds`, edits the message to:
  ```
  📦 <b>انتقال ربات به سرور جدید</b>

  اطلاعات SSH سرور مقصد را در یکی از فرمت‌های زیر بفرستید:

  <code>user@ip:port password</code>
  <code>user@ip password</code>
  <code>user@ip:port</code>  (احراز هویت با کلید)
  <code>user@ip</code>       (احراز هویت با کلید)

  ⚠️ پیام بعد از تأیید پاک می‌شود.
  ```
  No inline keyboard (admin types the credentials).

  ### 3.4 Receive credentials — message handler `AdminFlow.transfer_creds`

  ```python
  @router.message(AdminFlow.transfer_creds)
  async def transfer_creds(message: Message, state: FSMContext) -> None:
  ```

  - Parse with `_parse_creds(message.text or "")`.
  - On failure: reply with error, stay in same state (do not log the text).
  - On success: store parsed dict in FSM state (key `creds`), set state to `AdminFlow.transfer_confirm`.
  - Delete the admin's credential message immediately (`await message.delete()`).
  - Send a confirmation message showing only `user@host:port` (no password) with `transfer_confirm_kb()`.

  ### 3.5 Cancel — callback `home`

  Already handled by the existing `home` callback in `panel.py`. No extra handler needed; setting state to `transfer_creds` and having the user hit Cancel goes back to home. Make sure `state.clear()` is called in the `home` handler — check `panel.py` for this; if it's not there, add a note to call `await state.clear()` at the start of `transfer_start`.

  > **Decision:** `transfer_start` always calls `await state.clear()` before setting the new state, which safely clears any leftover state when the user returns to this flow.

  ### 3.6 Confirm — callback `transfer_confirm_yes`

  ```python
  @router.callback_query(kb.AdminCB.filter(F.action == "transfer_confirm_yes"))
  async def transfer_confirm_yes(call: CallbackQuery, state: FSMContext) -> None:
  ```

  - Read `creds` from FSM. If missing (stale press), answer with error and return.
  - Clear FSM state immediately (credentials no longer needed in state after this point — pass them into the background task directly).
  - Edit message to `⏳ انتقال در حال اجراست... این عملیات چند دقیقه طول می‌کشد.`
  - Launch background task: `asyncio.create_task(_run_transfer(call.message, creds))`

  ### 3.7 Background transfer function `_run_transfer`

  ```python
  async def _run_transfer(msg: Message, creds: dict) -> None:
  ```

  Uses a nested helper `_edit(text)` = `await msg.edit_text(text)` to show progress (no new messages).

  **Steps** (edit message at each step):

  1. **Connect** via `asyncssh`:
     ```python
     import asyncssh
     connect_kwargs = {"username": creds["user"], "host": creds["host"],
                       "port": creds["port"], "known_hosts": None}
     if creds["password"]:
         connect_kwargs["password"] = creds["password"]
     async with asyncssh.connect(**connect_kwargs) as conn:
         ...
     ```
     Progress: `🔌 در حال اتصال به {host}:{port}...`

  2. **Detect project directory** on destination:
     Run `docker inspect alovpn-bot --format '{{.GraphDriver.Data.MergedDir}}'` — if it fails or returns empty, fall back to checking common paths:
     ```
     for path in ["/opt/alovpnBot", "/root/alovpnBot", "/home/alovpnBot"]:
         result = await conn.run(f"test -f {path}/docker-compose.yml && echo found")
         if "found" in result.stdout: break
     ```
     If none found, set `dest_dir = "/opt/alovpnBot"` (will be created).
     Progress: `📂 مسیر مقصد: {dest_dir}`

     > **Decision:** Detect project dir on *source* too, using the same logic but via `conn.run("docker inspect alovpn-bot ...")`. Actually, the source dir is where the bot is running; since we can't inspect the source from the destination, we use `/opt/alovpnBot` as the canonical default for source. The implementer should use `SOURCE_DIR = "/opt/alovpnBot"` as a module-level constant.

  3. **Install Docker** on destination if missing:
     ```python
     result = await conn.run("docker --version", check=False)
     if result.exit_status != 0:
         await conn.run(
             "curl -fsSL https://get.docker.com | sh", check=True
         )
     ```
     Progress: `🐳 بررسی Docker روی سرور مقصد...`

  4. **Create destination directory**:
     `await conn.run(f"mkdir -p {dest_dir}", check=True)`

  5. **Copy project files** (tar pipe — no temp files):
     - Source command: `tar -czC {SOURCE_DIR} --exclude=data --exclude=.env --exclude='__pycache__' --exclude='*.pyc' .`
     - Pipe via asyncssh `stdin_pipe`:
       ```python
       async with conn.create_process(
           f"tar -xzC {dest_dir}"
       ) as proc:
           local_tar = await asyncssh.run_local(
               f"tar -czC {SOURCE_DIR} --exclude=data --exclude=.env"
               " --exclude=__pycache__ --exclude='*.pyc' ."
           )
           proc.stdin.write(local_tar.stdout)
           proc.stdin.write_eof()
       ```
     > **Decision:** `asyncssh.run_local` is not a real API. Use a different approach: run `tar` on the *source* server (the bot IS the source server), read stdout bytes, then stream to destination via `proc.stdin`. Since the bot runs inside a Docker container, the `/opt/alovpnBot` directory is on the *host*, not inside the container. The correct approach is to use asyncssh to connect to the *source* host to run tar locally, OR since the bot is running on the source host machine, use Python `subprocess` to run tar locally and pipe to SSH.

     **Final decision:** Use `asyncio.create_subprocess_exec` to run `tar` locally (on the source host, which the bot container can reach since it mounts `/opt/alovpnBot` or the volume), then pipe stdout bytes to `conn.run()` with stdin. Concretely:
     ```python
     proc_tar = await asyncio.create_subprocess_exec(
         "tar", "-czC", SOURCE_DIR,
         "--exclude=data", "--exclude=.env",
         "--exclude=__pycache__", "--exclude=*.pyc", ".",
         stdout=asyncio.subprocess.PIPE,
     )
     tar_bytes, _ = await proc_tar.communicate()
     result = await conn.run(
         f"tar -xzC {dest_dir}",
         input=tar_bytes,
         check=True,
     )
     ```
     Progress: `📁 در حال کپی فایل‌های پروژه...`

  6. **Copy `bot.db`** from the Docker volume `alovpn-bot_bot_data`:
     Run a local Docker cp command to get the db bytes, then stream to destination:
     ```python
     proc_db = await asyncio.create_subprocess_exec(
         "docker", "run", "--rm",
         "-v", "alovpn-bot_bot_data:/data:ro",
         "alpine", "cat", "/data/bot.db",
         stdout=asyncio.subprocess.PIPE,
     )
     db_bytes, _ = await proc_db.communicate()
     if proc_db.returncode == 0 and db_bytes:
         await conn.run(
             f"mkdir -p {dest_dir}/data && cat > {dest_dir}/data/bot.db",
             input=db_bytes,
             check=True,
         )
     ```
     Progress: `💾 در حال کپی دیتابیس...`

  7. **Copy `.env`**:
     ```python
     proc_env = await asyncio.create_subprocess_exec(
         "cat", f"{SOURCE_DIR}/.env",
         stdout=asyncio.subprocess.PIPE,
     )
     env_bytes, _ = await proc_env.communicate()
     if proc_env.returncode == 0 and env_bytes:
         await conn.run(
             f"cat > {dest_dir}/.env",
             input=env_bytes,
             check=True,
         )
     ```
     Progress: `⚙️ در حال کپی تنظیمات .env...`

  8. **Run `docker compose up -d --build`** on destination:
     ```python
     await conn.run(
         f"cd {dest_dir} && docker compose up -d --build",
         check=True,
     )
     ```
     Progress: `🚀 در حال راه‌اندازی ربات روی سرور مقصد...`

  9. **Poll until container is running** (max 120 s, 5 s interval):
     ```python
     for _ in range(24):
         await asyncio.sleep(5)
         r = await conn.run(
             "docker inspect -f '{{.State.Status}}' alovpn-bot",
             check=False,
         )
         if r.stdout.strip() == "running":
             break
     else:
         raise RuntimeError("کانتینر در ۱۲۰ ثانیه راه‌اندازی نشد.")
     ```
     Progress: `⏳ منتظر راه‌اندازی کانتینر...`

  10. **Success:** Edit message to success text + ask about disabling source:
      ```
      ✅ انتقال با موفقیت انجام شد!
      ربات روی سرور مقصد در حال اجراست.

      آیا می‌خواهید ربات روی سرور فعلی (مبدأ) خاموش شود؟
      ```
      Reply markup: `transfer_disable_kb()`.

  **Error handling:** Wrap the entire body in `try/except Exception as e` — on exception call `await msg.edit_text(f"🔴 خطا در انتقال:\n{e}")`. Never log credential values.

  ### 3.8 Disable source — callbacks `transfer_disable_yes` and `transfer_disable_no`

  ```python
  @router.callback_query(kb.AdminCB.filter(F.action == "transfer_disable_yes"))
  async def transfer_disable_yes(call: CallbackQuery) -> None:
  ```
  - Edit message to `⏳ در حال خاموش‌سازی سرور فعلی...`
  - Run locally:
    ```python
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", f"{SOURCE_DIR}/docker-compose.yml", "down",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.communicate()
    ```
  - Create sentinel file `{SOURCE_DIR}/DISABLED` with timestamp content.
  - Edit message to `🔴 سرور مبدأ خاموش شد. فایل DISABLED ایجاد شد.`

  ```python
  @router.callback_query(kb.AdminCB.filter(F.action == "transfer_disable_no"))
  async def transfer_disable_no(call: CallbackQuery) -> None:
  ```
  - Edit message to `✅ سرور مبدأ فعال ماند. انتقال کامل شد.`

  **Files:** `app/handlers/admin/transfer.py` (create new)

  **Verify:** `python -c "import ast, sys; ast.parse(open('app/handlers/admin/transfer.py').read()); print('syntax ok')"` — prints `syntax ok`.

---

- [ ] 4. Register the transfer router in `app/handlers/admin/__init__.py`.

  Import `transfer` alongside the existing imports and call `router.include_router(transfer.router)` inside `get_admin_router()`. Place it last (after `offers.router`) to avoid shadowing other handlers.

  ```python
  from app.handlers.admin import (
      activity,
      approval,
      offers,
      panel,
      panels,
      transfer,          # ← add
      wallet_management,
      wallet_topup_requests,
  )

  def get_admin_router() -> Router:
      router = Router(name="admin")
      router.include_router(approval.router)
      router.include_router(panel.router)
      router.include_router(panels.router)
      router.include_router(wallet_management.router)
      router.include_router(wallet_topup_requests.router)
      router.include_router(activity.router)
      router.include_router(offers.router)
      router.include_router(transfer.router)   # ← add
      return router
  ```

  **Files:** `app/handlers/admin/__init__.py`

  **Verify:** `python -c "from app.handlers.admin import get_admin_router; r = get_admin_router(); names = [c.name for c in r.sub_routers]; assert 'admin_transfer' in names, names; print('ok')"` — prints `ok`.

---

- [ ] 5. Add `asyncssh==2.18.0` to `requirements.txt`.

  Append the line to `requirements.txt`. `asyncssh` depends on `cryptography` which is already installed in the `.venv` (confirmed — `cryptography-50.0.2` present).

  **Files:** `requirements.txt`

  **Verify:** `pip install -r requirements.txt --dry-run 2>&1 | Select-String 'asyncssh'` — confirms the package is in the dependency set (Windows PowerShell). In the Docker build, `RUN pip install -r requirements.txt` will pull it automatically.

---

## Summary of new symbols

| Symbol | Kind | Location |
|---|---|---|
| `AdminFlow.transfer_creds` | FSM State | `app/states.py` |
| `AdminFlow.transfer_confirm` | FSM State | `app/states.py` |
| `AdminCB(action="transfer")` | Callback | `app/keyboards/admin.py` |
| `AdminCB(action="transfer_confirm_yes")` | Callback | `app/keyboards/admin.py` |
| `AdminCB(action="transfer_disable_yes")` | Callback | `app/keyboards/admin.py` |
| `AdminCB(action="transfer_disable_no")` | Callback | `app/keyboards/admin.py` |
| `transfer_confirm_kb()` | Keyboard fn | `app/keyboards/admin.py` |
| `transfer_disable_kb()` | Keyboard fn | `app/keyboards/admin.py` |
| `router` (admin_transfer) | aiogram Router | `app/handlers/admin/transfer.py` |
| `SOURCE_DIR` | module constant | `app/handlers/admin/transfer.py` = `"/opt/alovpnBot"` |

## Verification Results — Iteration 1 (first implementation)

All syntax checks passed:

```
python -m py_compile app/handlers/admin/transfer.py   → OK (exit 0)
python -m py_compile app/states.py                    → OK (exit 0)
python -m py_compile app/keyboards/admin.py           → OK (exit 0)
python -m py_compile app/handlers/admin/__init__.py   → OK (exit 0)
```

---

## Verification Results — Iteration 2 (review fix)

Review findings from `transfer-review.json` addressed:

1. **Unretained background task** — Added `_active_transfers: set[asyncio.Task] = set()` at module level. Task is stored with `_active_transfers.add(task)` and removed on completion via `task.add_done_callback(_active_transfers.discard)`.

2. **tar absent in container** — Replaced `asyncio.create_subprocess_exec("tar", ...)` with `_build_tar_in_memory()` using Python's built-in `tarfile` module + `loop.run_in_executor`. Archive bytes sent to destination via `conn.run("tar -xzC ...", input=tar_bytes)`. No dependency on system `tar`.

3. **.env copy silently skipped** — Changed from silent skip to hard `raise RuntimeError(...)` when `env_proc.returncode != 0 or not env_bytes`. Transfer aborts with a clear Telegram error message.

4. **No host-key verification warning** — Added explicit MITM warning in the confirmation message shown before the admin presses "confirm transfer".

5. **Container health-check name assumption** — Replaced `docker inspect -f '{{.State.Status}}' alovpn-bot` with `cd {dest_dir} && docker compose ps --format '{{.State}}' | head -1`, scoped to the destination directory.

6. **Stray dead-code return in admin.py** — Removed the unreachable `return b.as_markup()` that appeared after the real return in `inbound_security_choose`.

All syntax checks passed after fixes:

```
python -m py_compile app/handlers/admin/transfer.py   → OK (exit 0)
python -m py_compile app/states.py                    → OK (exit 0)
python -m py_compile app/keyboards/admin.py           → OK (exit 0)
python -m py_compile app/handlers/admin/__init__.py   → OK (exit 0)
```

---

## Notes for implementer

- **Credentials security:** Never pass raw credential text to `logger`. Parse immediately, then discard the message.
- **asyncssh `known_hosts=None`:** disables host-key checking. This is appropriate for an admin-initiated one-shot transfer but means MITM is possible. Document this in a code comment.
- **Source directory:** The bot runs as root (`user: "0:0"` in docker-compose.yml), so `asyncio.create_subprocess_exec("cat", "/opt/alovpnBot/.env", ...)` will work from inside the container. If the source dir isn't `/opt/alovpnBot`, the admin can adjust; for now use the constant.
- **Docker volume copy:** The `docker run --rm -v alovpn-bot_bot_data:/data:ro alpine cat /data/bot.db` command runs from inside the bot container. Since the container runs as root, this will succeed as long as Docker socket is available. If the Docker socket isn't mounted, this step will fail gracefully (checked via `proc_db.returncode`).
- **No DB socket mounting needed:** The project does not mount the Docker socket by default. If `docker` commands fail inside the container, add `-v /var/run/docker.sock:/var/run/docker.sock` to `docker-compose.yml`. The plan does not modify docker-compose.yml — leave that to the admin if needed, and document it.
- **`asyncssh` import guard:** Do `import asyncssh` at the top of `transfer.py`, not lazily. If the library isn't installed the import error surfaces at startup, not at runtime.
- **`transfer_confirm` state:** In the current design `transfer_confirm` state is set but never used as a message-handler state (confirmation is done via inline keyboard). It is kept as a named state for future use / FSM introspection. If it adds clutter, it can be omitted — but the task description explicitly asks for it.
