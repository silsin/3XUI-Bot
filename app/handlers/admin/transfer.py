"""انتقال ربات به سرور جدید از طریق تلگرام."""

from __future__ import annotations

import asyncio
import datetime
import io
import logging
import re
import tarfile

import asyncssh  # اگر نصب نباشد خطا در استارت ظاهر می‌شود، نه در زمان اجرا

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

# مسیر پیش‌فرض پروژه روی سرور مبدأ
SOURCE_DIR = "/opt/alovpnBot"

# نگه‌داری ارجاع به تسک‌های فعال تا GC آن‌ها را لغو نکند
_active_transfers: set[asyncio.Task] = set()

# ──────────────────────────────────────────────────────────────────────
# تجزیه اطلاعات اتصال SSH
# ──────────────────────────────────────────────────────────────────────

_CREDS_RE = re.compile(
    r"^([\w][\w.\-]*)@([\w.\-:]+?)(?::(\d+))?\s*(.*)$",
    re.DOTALL,
)


def _parse_creds(text: str) -> dict | None:
    """تجزیه اطلاعات SSH از متن ورودی.

    فرمت‌های پشتیبانی‌شده:
    - user@ip:port password
    - user@ip password
    - user@ip:port   (احراز هویت با کلید)
    - user@ip        (احراز هویت با کلید)

    مقدار برگشتی: dict با کلیدهای user، host، port، password
    یا None در صورت عدم تطابق.
    هیچ‌گاه متن خام ورودی لاگ نمی‌شود.
    """
    text = text.strip()
    m = _CREDS_RE.match(text)
    if not m:
        return None
    user, host, port_str, password_raw = m.groups()
    port = int(port_str) if port_str else 22
    password = password_raw.strip() or None
    return {"user": user, "host": host, "port": port, "password": password}


# ──────────────────────────────────────────────────────────────────────
# ساخت آرشیو پروژه در حافظه با tarfile پایتون (بدون وابستگی به tar سیستمی)
# ──────────────────────────────────────────────────────────────────────

_EXCLUDE_NAMES = {".git", ".venv", "__pycache__", "data", "DISABLED"}
_EXCLUDE_SUFFIXES = (".pyc", ".db")


def _build_tar_in_memory(source_dir: str) -> bytes:
    """فایل‌های پروژه را با tarfile پایتون فشرده می‌کند و بایت‌ها را برمی‌گرداند.

    استفاده از tarfile داخلی پایتون به جای اجرای tar سیستمی، وابستگی به
    نصب بودن tar در محیط Docker را حذف می‌کند.
    """
    import pathlib

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        root = pathlib.Path(source_dir)
        for path in root.rglob("*"):
            # حذف پوشه‌ها و فایل‌های استثنا
            rel = path.relative_to(root)
            parts = rel.parts
            if any(p in _EXCLUDE_NAMES for p in parts):
                continue
            if path.suffix in _EXCLUDE_SUFFIXES:
                continue
            if path.name == ".env":
                continue
            try:
                tar.add(str(path), arcname=str(rel))
            except OSError:
                pass  # فایل‌هایی که قابل خواندن نیستند نادیده گرفته می‌شوند
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────
# ورود به جریان انتقال
# ──────────────────────────────────────────────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "transfer"))
async def transfer_start(call: CallbackQuery, state: FSMContext) -> None:
    """شروع جریان انتقال: پاک‌سازی state و درخواست اطلاعات SSH."""
    await state.clear()
    await state.set_state(AdminFlow.transfer_creds)
    await call.message.edit_text(  # type: ignore[union-attr]
        "📦 <b>انتقال ربات به سرور جدید</b>\n\n"
        "اطلاعات SSH سرور مقصد را در یکی از فرمت‌های زیر بفرستید:\n\n"
        "<code>user@ip:port password</code>\n"
        "<code>user@ip password</code>\n"
        "<code>user@ip:port</code>  (احراز هویت با کلید)\n"
        "<code>user@ip</code>       (احراز هویت با کلید)\n\n"
        "⚠️ پیام بعد از تأیید پاک می‌شود.\n\n"
        "برای لغو روی ❌ لغو در صفحه تأیید بزنید.",
        parse_mode="HTML",
    )
    await call.answer()


# ──────────────────────────────────────────────────────────────────────
# دریافت اطلاعات اتصال
# ──────────────────────────────────────────────────────────────────────

@router.message(AdminFlow.transfer_creds)
async def transfer_creds_handler(message: Message, state: FSMContext) -> None:
    """تجزیه اطلاعات SSH، حذف پیام ادمین و نمایش تأییدیه."""
    creds = _parse_creds(message.text or "")

    # پاک‌سازی پیام ادمین قبل از هر چیز تا اطلاعات حساس در چت باقی نماند
    try:
        await message.delete()
    except Exception:
        pass  # اگر پیام قابل حذف نبود ادامه می‌دهیم

    if creds is None:
        await message.answer(
            "⚠️ فرمت وارد شده معتبر نیست.\n"
            "مثال: <code>root@1.2.3.4:22 mypassword</code>\n"
            "دوباره امتحان کنید.",
            parse_mode="HTML",
        )
        return

    await state.update_data(creds=creds)
    await state.set_state(AdminFlow.transfer_confirm)

    auth_type = "رمز عبور" if creds["password"] else "کلید SSH"
    await message.answer(
        f"🔍 <b>تأیید اطلاعات سرور مقصد</b>\n\n"
        f"🖥 آدرس: <code>{creds['host']}</code>\n"
        f"🔢 پورت: <code>{creds['port']}</code>\n"
        f"👤 کاربر: <code>{creds['user']}</code>\n"
        f"🔑 احراز هویت: {auth_type}\n\n"
        "🔴 <b>هشدار امنیتی مهم (حمله MITM):</b>\n"
        "هویت سرور مقصد تأیید <b>نمی‌شود</b> (known_hosts=None).\n"
        "یک مهاجم فعال روی مسیر شبکه می‌تواند قبل از برقراری رمزنگاری "
        "جایگزین شود و <b>توکن ربات، دیتابیس و محتوای .env</b> را "
        "شنود کند.\n\n"
        "⚠️ <b>تنها در شبکه خصوصی یا VPN</b> که کاملاً به آن اطمینان دارید "
        "ادامه دهید.\n\n"
        "آیا انتقال را تأیید می‌کنید؟",
        parse_mode="HTML",
        reply_markup=kb.transfer_confirm_kb(),
    )


@router.message(AdminFlow.transfer_confirm)
async def transfer_confirm_stray_message(message: Message, state: FSMContext) -> None:
    """پیام‌های تایپ‌شده در حالت انتظار تأیید — state را پاک می‌کند.

    اگر ادمین در حالت transfer_confirm پیامی تایپ کند (به جای زدن دکمه)،
    جریان لغو و اطلاعات اتصال از FSM پاک می‌شوند.
    """
    await state.clear()
    await message.answer(
        "⚠️ جریان انتقال لغو شد و اطلاعات اتصال پاک شدند.\n"
        "برای شروع مجدد روی 📦 انتقال به سرور جدید بزنید.",
        parse_mode="HTML",
        reply_markup=kb.back_home(),
    )


# ──────────────────────────────────────────────────────────────────────
# تأیید و شروع انتقال
# ──────────────────────────────────────────────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "transfer_confirm_yes"))
async def transfer_confirm_yes(call: CallbackQuery, state: FSMContext) -> None:
    """پاک‌سازی FSM و شروع انتقال در پس‌زمینه."""
    data = await state.get_data()
    creds = data.get("creds")
    if not creds:
        await call.answer("⚠️ اطلاعات اتصال یافت نشد. دوباره شروع کنید.", show_alert=True)
        await state.clear()
        return

    # پاک‌سازی state — اطلاعات حساس نباید در FSM بماند
    await state.clear()

    await call.message.edit_text(  # type: ignore[union-attr]
        "⏳ انتقال در حال اجراست...\nاین عملیات چند دقیقه طول می‌کشد.",
        parse_mode="HTML",
    )
    await call.answer()

    # ایجاد تسک و ذخیره ارجاع آن تا GC آن را لغو نکند
    # state به تابع پاس می‌شود تا پس از موفقیت transfer_done تنظیم شود
    task = asyncio.create_task(_run_transfer(call.message, creds, state))  # type: ignore[arg-type]
    _active_transfers.add(task)
    task.add_done_callback(_active_transfers.discard)


# ──────────────────────────────────────────────────────────────────────
# کشف نام واقعی Docker volume
# ──────────────────────────────────────────────────────────────────────

async def _find_bot_data_volume() -> str | None:
    """نام واقعی volume دیتابیس را از Docker کشف می‌کند.

    docker-compose.yml نام volume را bot_data اعلام می‌کند، اما Docker Compose
    آن را با پیشوند نام پروژه ترکیب می‌کند (مثلاً alovpnbot_bot_data).
    این تابع نام دقیق را از خروجی docker volume ls می‌خواند تا از
    عدم تطابق نام جلوگیری شود.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", "volume", "ls",
        "--filter", "name=bot_data",
        "--format", "{{.Name}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    lines = [line.strip() for line in stdout.decode(errors="replace").splitlines() if line.strip()]
    # انتخاب اول volume‌ای که نام آن شامل bot_data باشد
    for name in lines:
        if "bot_data" in name:
            return name
    return None


# ──────────────────────────────────────────────────────────────────────
# انتقال در پس‌زمینه
# ──────────────────────────────────────────────────────────────────────

async def _run_transfer(msg: Message, creds: dict, state: FSMContext) -> None:
    """تمام مراحل انتقال — ویرایش پیام در هر مرحله.

    هشدار امنیتی: known_hosts=None یعنی بررسی هویت سرور انجام نمی‌شود.
    این موضوع در صفحه تأییدیه به ادمین اطلاع‌رسانی شده است.
    """

    async def _edit(text: str) -> None:
        try:
            await msg.edit_text(text, parse_mode="HTML")
        except Exception:
            pass

    host = creds["host"]
    port = creds["port"]
    dest_dir = SOURCE_DIR  # مسیر پیش‌فرض در سرور مقصد

    try:
        # ── ۱. اتصال SSH ─────────────────────────────────────────────
        await _edit(f"🔌 در حال اتصال به <code>{host}:{port}</code>...")

        connect_kwargs: dict = {
            "host": host,
            "port": port,
            "username": creds["user"],
            "known_hosts": None,  # بررسی هویت غیرفعال — ادمین در صفحه تأیید آگاه شده است
        }
        if creds["password"]:
            connect_kwargs["password"] = creds["password"]

        async with asyncssh.connect(**connect_kwargs) as conn:

            # ── ۲. تشخیص مسیر پروژه روی مقصد ────────────────────────
            await _edit(f"🔌 متصل شد. در حال تشخیص مسیر پروژه روی <code>{host}</code>...")

            for candidate in ("/opt/alovpnBot", "/root/alovpnBot", "/home/alovpnBot"):
                r = await conn.run(
                    f"test -f {candidate}/docker-compose.yml && echo found",
                    check=False,
                )
                if "found" in (r.stdout or ""):
                    dest_dir = candidate
                    break

            await _edit(
                f"📂 مسیر مقصد: <code>{dest_dir}</code>\n\n"
                "🐳 بررسی Docker روی سرور مقصد..."
            )

            # ── ۳. نصب Docker در صورت نیاز ───────────────────────────
            r_docker = await conn.run("docker --version", check=False)
            if r_docker.exit_status != 0:
                await _edit("🐳 Docker پیدا نشد — در حال نصب (این چند دقیقه طول می‌کشد)...")
                await conn.run(
                    "curl -fsSL https://get.docker.com | sh",
                    check=True,
                )

            # ── ۳b. اطمینان از وجود tar روی سرور مقصد ────────────────
            # tar برای استخراج آرشیو پروژه الزامی است.
            r_tar = await conn.run("tar --version", check=False)
            if r_tar.exit_status != 0:
                await _edit("🔧 tar روی سرور مقصد پیدا نشد — در حال نصب...")
                # تلاش با apt-get (Debian/Ubuntu) و سپس apk (Alpine)
                r_apt = await conn.run(
                    "apt-get install -y tar 2>/dev/null || apk add --no-cache tar",
                    check=False,
                )
                if r_apt.exit_status != 0:
                    raise RuntimeError(
                        "نصب tar روی سرور مقصد ناموفق بود. "
                        "لطفاً tar را به صورت دستی نصب کنید."
                    )

            # ── ۴. ساخت پوشه مقصد ─────────────────────────────────────
            await conn.run(f"mkdir -p {dest_dir}", check=True)

            # ── ۵. کپی فایل‌های پروژه با tarfile پایتون ───────────────
            await _edit("📁 در حال فشرده‌سازی فایل‌های پروژه (tarfile پایتون)...")

            import pathlib

            source_path = pathlib.Path(SOURCE_DIR)
            if not source_path.is_dir():
                raise RuntimeError(
                    f"پوشه منبع پیدا نشد: {SOURCE_DIR}\n"
                    "مطمئن شوید که SOURCE_DIR در transfer.py درست تنظیم شده است."
                )

            # ساخت آرشیو در حافظه (در thread pool تا event loop را مسدود نکند)
            loop = asyncio.get_running_loop()
            tar_bytes = await loop.run_in_executor(
                None, _build_tar_in_memory, SOURCE_DIR
            )

            await _edit(
                f"📁 آرشیو آماده شد ({len(tar_bytes) // 1024} KB). "
                "در حال انتقال به سرور مقصد..."
            )

            # ارسال محتوای آرشیو از طریق SSH
            await conn.run(
                f"tar -xzC {dest_dir}",
                input=tar_bytes,
                check=True,
            )

            # ── ۶. کپی دیتابیس از volume ──────────────────────────────
            await _edit("💾 در حال کپی دیتابیس...")

            # کشف نام واقعی volume — از hardcode اجتناب می‌شود
            # زیرا Docker Compose نام پروژه را به volume اضافه می‌کند
            # (مثلاً alovpnbot_bot_data به جای alovpn-bot_bot_data)
            volume_name = await _find_bot_data_volume()
            if volume_name:
                db_proc = await asyncio.create_subprocess_exec(
                    "docker", "run", "--rm",
                    "-v", f"{volume_name}:/data:ro",
                    "alpine", "cat", "/data/bot.db",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                db_bytes, db_err = await db_proc.communicate()
                if db_proc.returncode == 0 and db_bytes:
                    await conn.run(
                        f"mkdir -p {dest_dir}/data && cat > {dest_dir}/data/bot.db",
                        input=db_bytes,
                        check=True,
                    )
                else:
                    # DB خالی یا خطا در خواندن — ادامه می‌دهیم، انتقال را متوقف نمی‌کنیم
                    logger.warning(
                        "کپی دیتابیس از volume ناموفق بود (returncode=%d)",
                        db_proc.returncode,
                    )
                    await _edit(
                        "⚠️ کپی دیتابیس از volume ناموفق بود — "
                        "احتمالاً Docker socket در دسترس نیست.\n"
                        "ادامه انتقال بدون دیتابیس..."
                    )
                    await asyncio.sleep(3)
            else:
                # volume پیدا نشد — هشدار می‌دهیم و ادامه می‌دهیم
                # (اگر Docker socket در دسترس نباشد این اتفاق می‌افتد)
                logger.warning("volume دیتابیس (bot_data) در این سرور پیدا نشد — مرحله DB نادیده گرفته شد")
                await _edit(
                    "⚠️ volume دیتابیس (bot_data) پیدا نشد.\n"
                    "انتقال بدون دیتابیس ادامه می‌یابد.\n"
                    "اگر Docker socket روی کانتینر سوار نشده، دیتابیس کپی نمی‌شود.\n\n"
                    "⚙️ در حال کپی تنظیمات .env..."
                )
                await asyncio.sleep(3)

            # ── ۷. کپی فایل .env — در صورت خطا انتقال متوقف می‌شود ────
            await _edit("⚙️ در حال کپی تنظیمات .env...")

            env_proc = await asyncio.create_subprocess_exec(
                "cat", f"{SOURCE_DIR}/.env",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            env_bytes, env_err = await env_proc.communicate()
            if env_proc.returncode != 0 or not env_bytes:
                raise RuntimeError(
                    "کپی فایل .env با خطا مواجه شد. "
                    "ربات روی مقصد بدون تنظیمات محیطی راه‌اندازی نخواهد شد.\n"
                    f"جزئیات: {env_err.decode(errors='replace')[:200]}"
                )

            await conn.run(
                f"cat > {dest_dir}/.env",
                input=env_bytes,
                check=True,
            )

            # ── ۸. اجرای docker compose روی مقصد ─────────────────────
            await _edit("🚀 در حال راه‌اندازی ربات روی سرور مقصد...")

            await conn.run(
                f"cd {dest_dir} && docker compose up -d --build",
                check=True,
            )

            # ── ۹. انتظار تا اجرای کانتینر (حداکثر ۱۲۰ ثانیه) ───────
            # از docker compose ps scoped به dest_dir استفاده می‌شود تا
            # وابستگی به نام خاص کانتینر حذف شود.
            await _edit("⏳ منتظر راه‌اندازی کانتینر...")

            container_up = False
            for _ in range(24):
                await asyncio.sleep(5)
                r_status = await conn.run(
                    f"cd {dest_dir} && docker compose ps --format '{{{{.State}}}}' | head -1",
                    check=False,
                )
                status = (r_status.stdout or "").strip()
                if status == "running":
                    container_up = True
                    break

            if not container_up:
                raise RuntimeError("کانتینر در ۱۲۰ ثانیه راه‌اندازی نشد.")

            # تأخیر کوتاه پس از running تا فرآیند راه‌اندازی درون کانتینر
            # (مهاجرت DB و غیره) تکمیل شود، قبل از اعلام موفقیت.
            await asyncio.sleep(5)

        # ── ۱۰. موفقیت ────────────────────────────────────────────────
        # ابتدا state را به transfer_done تنظیم می‌کنیم تا handler خاموش‌سازی
        # (transfer_disable_yes) فقط روی سرور مبدأ فعال باشد.
        await state.set_state(AdminFlow.transfer_done)

        await msg.edit_text(
            f"✅ <b>انتقال با موفقیت انجام شد!</b>\n"
            f"ربات روی سرور مقصد (<code>{host}</code>) در حال اجراست.\n\n"
            "آیا می‌خواهید ربات روی سرور فعلی (مبدأ) خاموش شود؟",
            parse_mode="HTML",
            reply_markup=kb.transfer_disable_kb(),
        )

    except Exception as e:
        # نوع خطا در لاگ سرور ثبت می‌شود؛ جزئیات حساس (نام کاربری، هاست) به تلگرام ارسال نمی‌شوند.
        logger.error("خطا در فرآیند انتقال: %s: %s", type(e).__name__, e)
        try:
            await msg.edit_text(
                "🔴 <b>خطا در انتقال</b>\n\n"
                "عملیات انتقال با مشکل مواجه شد. جزئیات در لاگ سرور ثبت شده‌اند.\n"
                "لطفاً از صحت اطلاعات SSH و دسترسی سرور مقصد اطمینان حاصل کنید.",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────
# خاموش‌سازی سرور مبدأ
# ──────────────────────────────────────────────────────────────────────

@router.callback_query(
    kb.AdminCB.filter(F.action == "transfer_disable_yes"),
    AdminFlow.transfer_done,
)
async def transfer_disable_yes(call: CallbackQuery, state: FSMContext) -> None:
    """خاموش کردن ربات روی سرور فعلی و ایجاد فایل DISABLED.

    محافظ FSM (AdminFlow.transfer_done) تضمین می‌کند که این callback
    فقط روی سرور مبدأ پردازش می‌شود، نه روی سرور مقصد که هنوز
    در حال اجرا است.

    پیام موفقیت را پیش از راه‌اندازی compose down ارسال می‌کنیم، چون
    compose down کانتینری را که این bot درون آن اجرا می‌شود می‌کشد
    و در اکثر شرایط ارسال پیام پس از آن هیچ‌گاه اتفاق نمی‌افتد.
    """
    await state.clear()

    # ── ۱. ابتدا پیام موفقیت را می‌فرستیم ────────────────────────────
    # این کار باید پیش از شروع compose down انجام شود چون compose down
    # فرآیند جاری (این ربات) را خاتمه می‌دهد.
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        await call.message.edit_text(  # type: ignore[union-attr]
            "🔴 سرور مبدأ در حال خاموش شدن است...\n"
            f"فایل <code>DISABLED</code> در <code>{SOURCE_DIR}</code> ایجاد شد.\n"
            f"زمان: <code>{timestamp}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer()

    # ── ۲. ایجاد فایل نشانگر قبل از خاموش‌سازی ──────────────────────
    try:
        disabled_path = f"{SOURCE_DIR}/DISABLED"
        write_proc = await asyncio.create_subprocess_exec(
            "sh", "-c", f"echo 'disabled at {timestamp}' > {disabled_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await write_proc.communicate()
    except Exception as e:
        logger.error("خطا در ایجاد فایل DISABLED: %s: %s", type(e).__name__, e)

    # ── ۳. خاموش‌سازی — fire-and-forget ─────────────────────────────
    # compose down این container را می‌کشد؛ منتظر communicate() نمی‌مانیم
    # چون ممکن است هیچ‌گاه برنگردد.
    try:
        await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", f"{SOURCE_DIR}/docker-compose.yml", "down",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:
        logger.error("خطا در اجرای compose down: %s: %s", type(e).__name__, e)


@router.callback_query(
    kb.AdminCB.filter(F.action == "transfer_disable_no"),
    AdminFlow.transfer_done,
)
async def transfer_disable_no(call: CallbackQuery, state: FSMContext) -> None:
    """ادمین تصمیم گرفت سرور مبدأ فعال بماند."""
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "✅ سرور مبدأ فعال ماند. انتقال کامل شد.",
        parse_mode="HTML",
    )
    await call.answer()
