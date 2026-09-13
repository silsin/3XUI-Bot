"""هندلرهای تأیید عضویت در کانال اجباری."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.keyboards import reply
from app.services import activity_service as activity
from app.services import settings_service as cfg
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
router = Router(name="channel")


async def check_channel_membership(bot, user_id: int, channel_username: str = "", channel_id: str = "") -> bool:
    """بررسی عضویت کاربر در کانال.
    
    Args:
        bot: نمونه بات
        user_id: شناسه کاربر
        channel_username: آیدی کانال (مثال: @channel)
        channel_id: شناسه عددی کانال
        
    Returns:
        True اگر کاربر عضو باشد، False در غیر این صورت
    """
    try:
        # اول با آیدی کانال امتحان کن
        if channel_id and channel_id.strip():
            try:
                channel_id_int = int(channel_id.strip())
                chat_member = await bot.get_chat_member(chat_id=channel_id_int, user_id=user_id)
                return chat_member.status in ["member", "administrator", "creator"]
            except (ValueError, TelegramBadRequest):
                pass
        
        # اگر با آیدی عددی نشد، با آیدی متنی امتحان کن
        if channel_username and channel_username.strip():
            try:
                # حذف @ از ابتدای آیدی اگر وجود دارد
                username = channel_username.strip().lstrip('@')
                chat_member = await bot.get_chat_member(chat_id=f"@{username}", user_id=user_id)
                return chat_member.status in ["member", "administrator", "creator"]
            except TelegramBadRequest as e:
                logger.warning(f"خطا در بررسی عضویت کانال: {e}")
                return False
        
        return False
    except Exception as e:
        logger.error(f"خطا در بررسی عضویت کانال: {e}")
        return False


@router.callback_query(F.data == "check_channel_membership")
async def callback_check_membership(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    is_admin: bool,
) -> None:
    """بررسی عضویت کاربر در کانال از طریق دکمه کال‌بک."""
    # بررسی فعال بودن سیستم کانال
    channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
    if not channel_enabled:
        # اگر سیستم غیرفعال باشد، اجازه دسترسی بده
        user.channel_verified = True
        await session.commit()
        await callback.answer(MSG_CHANNEL_VERIFIED, show_alert=True)
        await callback.message.answer(
            "خوش آمدید! اکنون می‌توانید از ربات استفاده کنید.",
            reply_markup=reply.main_menu(is_admin=is_admin)
        )
        return
    
    # دریافت اطلاعات کانال
    channel_username = await cfg.get(session, S_CHANNEL_USERNAME, "")
    channel_id = await cfg.get(session, S_CHANNEL_ID, "")
    channel_invite_link = await cfg.get(session, S_CHANNEL_INVITE_LINK, "")
    
    # اگر لینک دعوت موجود نباشد اما آیدی کانال موجود باشد
    if not channel_invite_link and channel_username:
        channel_invite_link = f"https://t.me/{channel_username.lstrip('@')}"
    
    # بررسی عضویت
    is_member = await check_channel_membership(
        callback.bot, user.id, channel_username, channel_id
    )
    
    if is_member:
        # اگر عضو است، تأیید کن
        user.channel_verified = True
        await session.commit()
        
        await callback.answer(MSG_CHANNEL_VERIFIED, show_alert=True)
        await callback.message.answer(
            MSG_CHANNEL_VERIFIED,
            reply_markup=reply.main_menu(is_admin=is_admin)
        )
        
        # لاگ فعالیت
        await activity.log_activity(session, user.id, activity.Actions.CHANNEL_VERIFIED)
    else:
        # اگر عضو نیست، دوباره پیام بده
        verification_text = await cfg.get(session, S_CHANNEL_VERIFICATION_TEXT, "")
        
        message_text = render(
            verification_text or MSG_CHANNEL_NOT_MEMBER,
            channel_link=channel_invite_link
        )
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_JOIN_CHANNEL, url=channel_invite_link),
                InlineKeyboardButton(text=BTN_CHECK_MEMBERSHIP, callback_data="check_channel_membership")
            ]
        ])
        
        await callback.answer("شما هنوز عضو کانال نیستید!", show_alert=True)
        await callback.message.edit_text(message_text, reply_markup=keyboard)


@router.message(Command("check_channel"))
async def cmd_check_channel(
    message: Message,
    session: AsyncSession,
    user: User,
    is_admin: bool,
) -> None:
    """دستور بررسی عضویت در کانال."""
    # بررسی فعال بودن سیستم کانال
    channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
    if not channel_enabled:
        await message.answer("سیستم کانال اجباری غیرفعال است.")
        return
    
    # دریافت اطلاعات کانال
    channel_username = await cfg.get(session, S_CHANNEL_USERNAME, "")
    channel_id = await cfg.get(session, S_CHANNEL_ID, "")
    channel_invite_link = await cfg.get(session, S_CHANNEL_INVITE_LINK, "")
    
    # اگر لینک دعوت موجود نباشد اما آیدی کانال موجود باشد
    if not channel_invite_link and channel_username:
        channel_invite_link = f"https://t.me/{channel_username.lstrip('@')}"
    
    # بررسی عضویت
    is_member = await check_channel_membership(
        message.bot, user.id, channel_username, channel_id
    )
    
    if is_member:
        # اگر عضو است، تأیید کن
        user.channel_verified = True
        await session.commit()
        
        await message.answer(
            MSG_CHANNEL_VERIFIED,
            reply_markup=reply.main_menu(is_admin=is_admin)
        )
        
        # لاگ فعالیت
        await activity.log_activity(session, user.id, activity.Actions.CHANNEL_VERIFIED)
    else:
        # اگر عضو نیست، پیام بده
        verification_text = await cfg.get(session, S_CHANNEL_VERIFICATION_TEXT, "")
        
        message_text = render(
            verification_text or MSG_CHANNEL_NOT_MEMBER,
            channel_link=channel_invite_link
        )
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_JOIN_CHANNEL, url=channel_invite_link),
                InlineKeyboardButton(text=BTN_CHECK_MEMBERSHIP, callback_data="check_channel_membership")
            ]
        ])
        
        await message.answer(message_text, reply_markup=keyboard)


@router.message(F.text == "بررسی عضویت")
async def text_check_membership(
    message: Message,
    session: AsyncSession,
    user: User,
    is_admin: bool,
) -> None:
    """بررسی عضویت با متن «بررسی عضویت»."""
    await cmd_check_channel(message, session, user, is_admin)