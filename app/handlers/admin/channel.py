"""مدیریت کانال اجباری در پنل ادمین."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.filters import IsAdmin
from app.keyboards import admin as kb
from app.services import settings_service as cfg
from app.states import AdminFlow
from app.texts import (
    BTN_CHECK_MEMBERSHIP,
    BTN_JOIN_CHANNEL,
    MSG_CHANNEL_CHECK_FAILED,
    MSG_CHANNEL_NOT_MEMBER,
    MSG_CHANNEL_VERIFIED,
    S_CHANNEL_ENABLED,
    S_CHANNEL_ID,
    S_CHANNEL_INVITE_LINK,
    S_CHANNEL_USERNAME,
    S_CHANNEL_VERIFICATION_TEXT,
)
from app.utils.formatting import render

logger = logging.getLogger(__name__)
router = Router(name="admin_channel")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

CHANNEL_FIELDS = [
    (S_CHANNEL_ENABLED, "وضعیت کانال اجباری"),
    (S_CHANNEL_USERNAME, "آیدی کانال (مثال: @channel)"),
    (S_CHANNEL_ID, "شناسه عددی کانال"),
    (S_CHANNEL_INVITE_LINK, "لینک دعوت کانال"),
    (S_CHANNEL_VERIFICATION_TEXT, "متن درخواست عضویت"),
]


# ---------- صفحه اصلی مدیریت کانال ----------


@router.callback_query(kb.AdminCB.filter(F.action == "channel"))
async def channel_home(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش صفحه اصلی مدیریت کانال."""
    channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
    channel_username = await cfg.get(session, S_CHANNEL_USERNAME, "")
    channel_id = await cfg.get(session, S_CHANNEL_ID, "")
    channel_invite_link = await cfg.get(session, S_CHANNEL_INVITE_LINK, "")
    
    status_text = "🟢 فعال" if channel_enabled else "🔴 غیرفعال"
    
    if not channel_invite_link and channel_username:
        channel_invite_link = f"https://t.me/{channel_username.lstrip('@')}"
    
    text = (
        f"📢 <b>مدیریت کانال اجباری</b>\n\n"
        f"وضعیت: {status_text}\n"
        f"آیدی کانال: {channel_username or '—'}\n"
        f"شناسه عددی: {channel_id or '—'}\n"
        f"لینک دعوت: {channel_invite_link or '—'}\n\n"
        f"با فعال کردن این قابلیت، کاربران باید در کانال مشخص‌شده عضو باشند "
        f"تا بتوانند از ربات استفاده کنند."
    )
    
    await call.message.edit_text(text, reply_markup=kb.channel_management())
    await call.answer()


# ---------- فعال/غیرفعال کردن کانال ----------


@router.callback_query(kb.AdminCB.filter(F.action == "channel_toggle"))
async def channel_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    """تغییر وضعیت فعال/غیرفعال بودن کانال اجباری."""
    channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
    new_value = "0" if channel_enabled else "1"
    await cfg.set_value(session, S_CHANNEL_ENABLED, new_value)
    
    # ریست کردن وضعیت تأیید همه کاربران اگر کانال غیرفعال شود
    if not channel_enabled:  # یعنی قبلاً غیرفعال بود و الان فعال شده
        await call.answer("کانال اجباری فعال شد.")
    else:  # قبلاً فعال بود و الان غیرفعال شده
        # ریست کردن وضعیت تأیید همه کاربران
        from sqlalchemy import update
        stmt = update(User).values(channel_verified=False)
        await session.execute(stmt)
        await session.commit()
        await call.answer("کانال اجباری غیرفعال شد و وضعیت تأیید همه کاربران ریست شد.")
    
    await channel_home(call, session)


# ---------- ویرایش تنظیمات کانال ----------


@router.callback_query(kb.AdminCB.filter(F.action == "channel_edit_list"))
async def channel_edit_list(call: CallbackQuery) -> None:
    """نمایش لیست تنظیمات کانال برای ویرایش."""
    from app.keyboards import admin as kb
    await call.message.edit_text(
        "📝 کدام تنظیمات کانال را ویرایش می‌کنید؟",
        reply_markup=kb.channel_edit_list(),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "edit"))
async def channel_edit_prompt(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession, state: FSMContext
) -> None:
    """نمایش صفحه ویرایش یک تنظیمات کانال."""
    key = callback_data.field
    
    # تعیین نوع فیلد برای نمایش راهنما
    is_bool = key == S_CHANNEL_ENABLED
    is_numeric = key == S_CHANNEL_ID
    
    current = await cfg.get(session, key)
    
    await state.set_state(AdminFlow.editing_channel_setting)
    await state.update_data(key=key)
    
    field_labels = dict(CHANNEL_FIELDS)
    field_name = field_labels.get(key, key)
    
    if is_bool:
        await call.message.answer(
            f"تنظیمات: <b>{field_name}</b>\n"
            f"مقدار فعلی: {'فعال' if await cfg.get_bool(session, key, False) else 'غیرفعال'}\n\n"
            f"مقدار جدید را ارسال کنید:\n"
            f"- برای فعال کردن: '1', 'true', 'yes', 'on', یا 'بله'\n"
            f"- برای غیرفعال کردن: '0', 'false', 'no', 'off', یا 'خیر'"
        )
    elif is_numeric:
        await call.message.answer(
            f"تنظیمات: <b>{field_name}</b>\n"
            f"مقدار فعلی: {current or '—'}\n\n"
            f"مقدار جدید را ارسال کنید (فقط عدد):"
        )
    else:
        await call.message.answer(
            f"تنظیمات: <b>{field_name}</b>\n"
            f"مقدار فعلی:\n<code>{current or '—'}</code>\n\n"
            f"مقدار جدید را ارسال کنید:"
        )
    
    await call.answer()


@router.message(AdminFlow.editing_channel_setting)
async def channel_edit_save(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """ذخیره تنظیمات ویرایش‌شده کانال."""
    data = await state.get_data()
    key = data.get("key", "")
    value = message.text or message.caption or ""
    
    if key == S_CHANNEL_ENABLED:
        # برای فیلد بولین، مقادیر مختلف را بررسی کن
        value_lower = value.strip().lower()
        bool_value = value_lower in {"1", "true", "yes", "on", "بله", "فعال"}
        await cfg.set_value(session, key, "1" if bool_value else "0")
        
        # اگر کانال غیرفعال شد، وضعیت تأیید همه کاربران را ریست کن
        if not bool_value:
            from sqlalchemy import update
            stmt = update(User).values(channel_verified=False)
            await session.execute(stmt)
            await session.commit()
    elif key == S_CHANNEL_ID:
        # برای شناسه عددی، فقط عدد بپذیر
        if value.strip().isdigit() or not value.strip():
            await cfg.set_value(session, key, value.strip())
        else:
            await message.answer("⚠️ لطفاً فقط عدد وارد کنید.")
            return
    else:
        await cfg.set_value(session, key, value.strip())
    
    await state.clear()
    await message.answer("✅ تنظیمات کانال ذخیره شد.", reply_markup=kb.back_home())


# ---------- نمایش لیست کاربران تایید نشده ----------


@router.callback_query(kb.AdminCB.filter(F.action == "channel_unverified"))
async def show_unverified_users(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش لیست کاربرانی که عضویت کانال را تأیید نکرده‌اند."""
    from sqlalchemy import select
    
    # بررسی فعال بودن سیستم کانال
    channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
    if not channel_enabled:
        await call.message.edit_text(
            "⚠️ سیستم کانال اجباری غیرفعال است.",
            reply_markup=kb.back_home()
        )
        await call.answer()
        return
    
    # دریافت کاربران تأیید نشده
    stmt = (
        select(User)
        .where(User.channel_verified.is_(False))
        .order_by(User.created_at.desc())
        .limit(50)
    )
    users = list((await session.execute(stmt)).scalars().all())
    
    if not users:
        await call.message.edit_text(
            "✅ همه کاربران عضویت کانال را تأیید کرده‌اند.",
            reply_markup=kb.back_home()
        )
        await call.answer()
        return
    
    # ساخت پیام لیست
    lines = []
    for i, user in enumerate(users[:20], 1):  # فقط ۲۰ کاربر اول
        uname = f"@{user.username}" if user.username else "بدون یوزرنیم"
        lines.append(
            f"{i}. {user.first_name or '—'} ({uname}) - <code>{user.id}</code>"
        )
    
    text = (
        f"👥 <b>کاربران تأیید نشده</b> (تعداد: {len(users)})\n\n"
        + "\n".join(lines)
    )
    
    if len(users) > 20:
        text += f"\n\n... و {len(users) - 20} کاربر دیگر"
    
    await call.message.edit_text(text, reply_markup=kb.back_home())
    await call.answer()


# ---------- تأیید دستی کاربر ----------


@router.callback_query(kb.AdminCB.filter(F.action == "channel_verify_user"))
async def channel_verify_user_prompt(
    call: CallbackQuery, state: FSMContext
) -> None:
    """درخواست شناسه کاربر برای تأیید دستی."""
    await state.set_state(AdminFlow.channel_verify_user)
    await call.message.answer(
        "🔎 شناسه عددی کاربر را برای تأیید دستی عضویت کانال ارسال کنید:"
    )
    await call.answer()


@router.message(AdminFlow.channel_verify_user)
async def channel_verify_user_save(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot
) -> None:
    """تأیید دستی عضویت کاربر در کانال."""
    await state.clear()
    user_id_str = message.text.strip()
    
    if not user_id_str.isdigit():
        await message.answer("⚠️ لطفاً فقط شناسه عددی کاربر ارسال کنید.")
        return
    
    user_id = int(user_id_str)
    user = await session.get(User, user_id)
    
    if not user:
        await message.answer("❌ کاربر با این شناسه یافت نشد.")
        return
    
    # بررسی فعال بودن سیستم کانال
    channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
    if not channel_enabled:
        await message.answer("⚠️ سیستم کانال اجباری غیرفعال است.")
        return
    
    # تأیید کاربر
    user.channel_verified = True
    await session.commit()
    
    # اطلاع به کاربر
    try:
        await bot.send_message(
            user.id,
            "✅ مدیر عضویت شما در کانال اجباری را به صورت دستی تأیید کرد.\n"
            "اکنون می‌توانید از ربات استفاده کنید."
        )
    except Exception as e:
        logger.warning(f"ناتوان در اطلاع به کاربر {user.id}: {e}")
    
    await message.answer(
        f"✅ عضویت کاربر <code>{user_id}</code> در کانال تأیید شد.\n"
        f"نام: {user.first_name or '—'}\n"
        f"یوزرنیم: @{user.username or '—'}",
        reply_markup=kb.back_home()
    )


# ---------- تست عضویت کانال ----------


@router.callback_query(kb.AdminCB.filter(F.action == "channel_test"))
async def channel_test_membership(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """تست عضویت ادمین در کانال."""
    # بررسی فعال بودن سیستم کانال
    channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
    if not channel_enabled:
        await call.message.edit_text(
            "⚠️ سیستم کانال اجباری غیرفعال است.",
            reply_markup=kb.back_home()
        )
        await call.answer()
        return
    
    # دریافت اطلاعات کانال
    channel_username = await cfg.get(session, S_CHANNEL_USERNAME, "")
    channel_id = await cfg.get(session, S_CHANNEL_ID, "")
    channel_invite_link = await cfg.get(session, S_CHANNEL_INVITE_LINK, "")
    
    # اگر لینک دعوت موجود نباشد اما آیدی کانال موجود باشد
    if not channel_invite_link and channel_username:
        channel_invite_link = f"https://t.me/{channel_username.lstrip('@')}"
    
    if not channel_username and not channel_id:
        await call.message.edit_text(
            "❌ هیچ آیدی یا شناسه کانالی تنظیم نشده است.",
            reply_markup=kb.back_home()
        )
        await call.answer()
        return
    
    # تست عضویت ادمین
    from app.handlers.channel import check_channel_membership
    
    is_member = await check_channel_membership(
        call.bot, call.from_user.id, channel_username, channel_id
    )
    
    if is_member:
        await call.message.edit_text(
            f"✅ شما عضو کانال هستید!\n\n"
            f"آیدی کانال: {channel_username or '—'}\n"
            f"شناسه عددی: {channel_id or '—'}\n"
            f"لینک دعوت: {channel_invite_link or '—'}",
            reply_markup=kb.back_home()
        )
    else:
        await call.message.edit_text(
            f"❌ شما عضو کانال نیستید!\n\n"
            f"آیدی کانال: {channel_username or '—'}\n"
            f"شناسه عددی: {channel_id or '—'}\n"
            f"لینک دعوت: {channel_invite_link or '—'}\n\n"
            f"لطفاً ابتدا در کانال عضو شوید.",
            reply_markup=kb.back_home()
        )
    
    await call.answer()