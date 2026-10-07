"""انتقال ربات به سرور جدید از طریق تلگرام."""

from __future__ import annotations

import asyncio
import datetime
import logging
import re

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

# مسیر پیش‌فرض پروژه روی سرور مبدأ (قابل تغییر از طریق متغیر محیطی نیست؛
# اگر مسیر متفاوت است ادمین باید docker-compose.yml را بررسی کند).
SOURCE_DIR = "/opt/alovpnBot"

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
        "⚠️ پیام بعد از تأیید پاک می‌شود.",
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

    # پاک‌سازی پیام ادمین قبل از هر چیز
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
        "آیا انتقال را تأیید می‌کنید؟",
        parse_mode="HTML",
        reply_markup=kb.transfer_confirm_kb(),
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

    # اجرا در پس‌زمینه تا ربات پاسخ‌گو بماند
    asyncio.create_task(_run_transfer(call.message, creds))  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# انتقال در پس‌زمینه
# ──────────────────────────────────────────────────────────────────────

async def _run_transfer(msg: Message, creds: dict) -> None:
    """تمام مراحل انتقال — ویرایش پیام در هر مرحله.

    هشدار امنیتی: known_hosts=None یعنی بررسی هویت سرور انجام نمی‌شود.
    این برای یک انتقال یک‌بار توسط ادمین قابل قبول است اما MITM را ممکن می‌سازد.
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
            "known_hosts": None,  # بررسی هویت غیرفعال — ببینید هشدار بالا
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

            await _edit(f"📂 مسیر مقصد: <code>{dest_dir}</code>\n\n🐳 بررسی Docker روی سرور مقصد...")

            # ── ۳. نصب Docker در صورت نیاز ───────────────────────────
            r_docker = await conn.run("docker --version", check=False)
            if r_docker.exit_status != 0:
                await _edit("🐳 Docker پیدا نشد — در حال نصب (این چند دقیقه طول می‌کشد)...")
                await conn.run(
                    "curl -fsSL https://get.docker.com | sh",
                    check=True,
                )

            # ── ۴. ساخت پوشه مقصد ─────────────────────────────────────
            await conn.run(f"mkdir -p {dest_dir}", check=True)

            # ── ۵. کپی فایل‌های پروژه با tar pipe ────────────────────
            await _edit("📁 در حال کپی فایل‌های پروژه...")

            tar_proc = await asyncio.create_subprocess_exec(
                "tar", "-czC", SOURCE_DIR,
                "--exclude=data",
                "--exclude=.env",
                "--exclude=.git",
                "--exclude=.venv",
                "--exclude=__pycache__",
                "--exclude=*.pyc",
                "--exclude=*.db",
                "--exclude=DISABLED",
                ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            tar_bytes, tar_err = await tar_proc.communicate()
            if tar_proc.returncode != 0:
                raise RuntimeError(
                    f"خطا در فشرده‌سازی فایل‌ها:\n{tar_err.decode(errors='replace')[:300]}"
                )

            await conn.run(
                f"tar -xzC {dest_dir}",
                input=tar_bytes,
                check=True,
            )

            # ── ۶. کپی دیتابیس از volume ──────────────────────────────
            await _edit("💾 در حال کپی دیتابیس...")

            db_proc = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm",
                "-v", "alovpn-bot_bot_data:/data:ro",
                "alpine", "cat", "/data/bot.db",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            db_bytes, _ = await db_proc.communicate()
            if db_proc.returncode == 0 and db_bytes:
                await conn.run(
                    f"mkdir -p {dest_dir}/data && cat > {dest_dir}/data/bot.db",
                    input=db_bytes,
                    check=True,
                )
            else:
                logger.warning("کپی دیتابیس از volume انجام نشد (احتمالاً Docker socket در دسترس نیست)")

            # ── ۷. کپی فایل .env ──────────────────────────────────────
            await _edit("⚙️ در حال کپی تنظیمات .env...")

            env_proc = await asyncio.create_subprocess_exec(
                "cat", f"{SOURCE_DIR}/.env",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            env_bytes, _ = await env_proc.communicate()
            if env_proc.returncode == 0 and env_bytes:
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
            await _edit("⏳ منتظر راه‌اندازی کانتینر...")

            for _ in range(24):
                await asyncio.sleep(5)
                r_status = await conn.run(
                    "docker inspect -f '{{.State.Status}}' alovpn-bot",
                    check=False,
                )
                if (r_status.stdout or "").strip() == "running":
                    break
            else:
                raise RuntimeError("کانتینر در ۱۲۰ ثانیه راه‌اندازی نشد.")

        # ── ۱۰. موفقیت ────────────────────────────────────────────────
        await msg.edit_text(
            f"✅ <b>انتقال با موفقیت انجام شد!</b>\n"
            f"ربات روی سرور مقصد (<code>{host}</code>) در حال اجراست.\n\n"
            "آیا می‌خواهید ربات روی سرور فعلی (مبدأ) خاموش شود؟",
            parse_mode="HTML",
            reply_markup=kb.transfer_disable_kb(),
        )

    except Exception as e:
        # هیچ‌گاه مقادیر اطلاعات حساس لاگ نمی‌شوند
        logger.error("خطا در فرآیند انتقال: %s", type(e).__name__)
        try:
            await msg.edit_text(
                f"🔴 <b>خطا در انتقال:</b>\n<code>{str(e)[:500]}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────
# خاموش‌سازی سرور مبدأ
# ──────────────────────────────────────────────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "transfer_disable_yes"))
async def transfer_disable_yes(call: CallbackQuery) -> None:
    """خاموش کردن ربات روی سرور فعلی و ایجاد فایل DISABLED."""
    await call.message.edit_text(  # type: ignore[union-attr]
        "⏳ در حال خاموش‌سازی سرور فعلی...",
        parse_mode="HTML",
    )
    await call.answer()

    try:
        down_proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", f"{SOURCE_DIR}/docker-compose.yml", "down",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await down_proc.communicate()

        # ایجاد فایل نشانگر
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        disabled_path = f"{SOURCE_DIR}/DISABLED"
        write_proc = await asyncio.create_subprocess_exec(
            "sh", "-c", f"echo 'disabled at {timestamp}' > {disabled_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await write_proc.communicate()

        await call.message.edit_text(  # type: ignore[union-attr]
            "🔴 سرور مبدأ خاموش شد.\n"
            f"فایل <code>DISABLED</code> در <code>{SOURCE_DIR}</code> ایجاد شد.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("خطا در خاموش‌سازی سرور مبدأ: %s", type(e).__name__)
        try:
            await call.message.edit_text(  # type: ignore[union-attr]
                f"🔴 <b>خطا در خاموش‌سازی:</b>\n<code>{str(e)[:400]}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.callback_query(kb.AdminCB.filter(F.action == "transfer_disable_no"))
async def transfer_disable_no(call: CallbackQuery) -> None:
    """ادمین تصمیم گرفت سرور مبدأ فعال بماند."""
    await call.message.edit_text(  # type: ignore[union-attr]
        "✅ سرور مبدأ فعال ماند. انتقال کامل شد.",
        parse_mode="HTML",
    )
    await call.answer()
