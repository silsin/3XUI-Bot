"""میدلورها: نشست دیتابیس، ثبت کاربر و کنترل مسدودی."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User as TgUser

from app.config import get_settings
from app.db.models import User
from app.db.session import get_sessionmaker
from app.texts import MSG_BLOCKED

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """برای هر آپدیت یک نشست ساخته و در data قرار می‌دهد."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            data["session"] = session
            return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    """کاربر را ثبت/به‌روزرسانی می‌کند و در data می‌گذارد. مسدودها را رد می‌کند."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session = data.get("session")
        if tg_user is None or session is None or tg_user.is_bot:
            return await handler(event, data)

        user = await session.get(User, tg_user.id)
        if user is None:
            user = User(
                id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
            session.add(user)
            await session.commit()
        else:
            changed = False
            if user.username != tg_user.username:
                user.username = tg_user.username
                changed = True
            if user.first_name != tg_user.first_name:
                user.first_name = tg_user.first_name
                changed = True
            if changed:
                await session.commit()

        settings = get_settings()
        data["user"] = user
        data["is_admin"] = settings.is_admin(tg_user.id)

        if user.is_blocked and not data["is_admin"]:
            if isinstance(event, Update) and event.message:
                await event.message.answer(MSG_BLOCKED)
            elif isinstance(event, Update) and event.callback_query:
                await event.callback_query.answer(MSG_BLOCKED, show_alert=True)
            return None

        return await handler(event, data)
class ChannelVerificationMiddleware(BaseMiddleware):
    """بررسی عضویت کاربر در کانال اجباری قبل از دسترسی به ربات."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            tg_user: TgUser | None = data.get("event_from_user")
            session = data.get("session")
            user = data.get("user")
            is_admin = data.get("is_admin", False)
            
            # اگر کاربر وجود نداشته باشد یا ادمین باشد، اجازه دسترسی بده
            if tg_user is None or session is None or tg_user.is_bot or is_admin:
                return await handler(event, data)

            # اگر کاربر مسدود شده باشد، قبلاً در UserMiddleware بررسی شده
            if user and user.is_blocked:
                return await handler(event, data)

            # بررسی فعال بودن سیستم کانال اجباری
            from app.services import settings_service as cfg
            from app.texts import S_CHANNEL_ENABLED
            
            channel_enabled = await cfg.get_bool(session, S_CHANNEL_ENABLED, False)
            
            # اگر سیستم کانال غیرفعال باشد، اجازه دسترسی بده
            if not channel_enabled:
                return await handler(event, data)

            # اگر کاربر قبلاً تأیید شده باشد، اجازه دسترسی بده
            if user and hasattr(user, 'channel_verified') and user.channel_verified:
                return await handler(event, data)

            # اگر پیام از نوع پیام متنی یا کال‌بک نباشد (مثلاً کامند)، اجازه بده
            from aiogram.types import Message, CallbackQuery
            
            if not isinstance(event, (Message, CallbackQuery)):
                return await handler(event, data)

            # بررسی اینکه آیا کاربر سعی می‌کند عضویت خود را تأیید کند
            if isinstance(event, CallbackQuery) and event.data and "check_channel" in event.data:
                return await handler(event, data)
            
            if isinstance(event, Message) and event.text:
                text = event.text.strip()
                if text in ["بررسی عضویت", "/check_channel", "/start"]:
                    return await handler(event, data)
            
            # در غیر این صورت، کاربر باید ابتدا عضویت خود را تأیید کند
            from app.texts import S_CHANNEL_USERNAME, S_CHANNEL_INVITE_LINK, S_CHANNEL_VERIFICATION_TEXT
            from app.texts import BTN_CHECK_MEMBERSHIP, BTN_JOIN_CHANNEL, MSG_CHANNEL_NOT_MEMBER
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from app.utils.formatting import render
            
            channel_username = await cfg.get(session, S_CHANNEL_USERNAME, "")
            channel_invite_link = await cfg.get(session, S_CHANNEL_INVITE_LINK, "")
            verification_text = await cfg.get(session, S_CHANNEL_VERIFICATION_TEXT, "")
            
            # اگر لینک دعوت موجود نباشد اما آیدی کانال موجود باشد
            if not channel_invite_link and channel_username:
                channel_invite_link = f"https://t.me/{channel_username.lstrip('@')}"
            
            # اگر هیچ لینکی موجود نباشد، گذاشت بده
            if not channel_invite_link:
                logger.warning("کانال اجباری فعال است اما لینک دعوت تنظیم نشده است.")
                return await handler(event, data)
            
            # نمایش پیام درخواست عضویت
            message_text = render(
                verification_text or MSG_CHANNEL_NOT_MEMBER,
                channel_link=channel_invite_link
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=BTN_JOIN_CHANNEL, url=channel_invite_link),
                    InlineKeyboardButton(text=BTN_CHECK_MEMBERSHIP, callback_data="check_channel_membership")
                ]
            ])
            
            if isinstance(event, Message):
                await event.answer(message_text, reply_markup=keyboard)
            elif isinstance(event, CallbackQuery):
                await event.message.answer(message_text, reply_markup=keyboard)
                await event.answer()
            
            return None
        except Exception as e:
            logger.error(f"خطا در ChannelVerificationMiddleware: {e}")
            return await handler(event, data)