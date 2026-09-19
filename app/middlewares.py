"""میدلورها: نشست دیتابیس، ثبت کاربر و کنترل مسدودی."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User as TgUser

from app.config import get_settings
from app.db.models import User
from app.db.session import get_sessionmaker
from app.texts import MSG_BLOCKED, S_REQUIRED_CHANNEL_ENABLED, S_REQUIRED_CHANNEL_ID

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



class ChannelMembershipMiddleware(BaseMiddleware):
    """چک می‌کند که کاربر عضو کانال الزامی است یا خیر.
    
    اگر کانال الزامی فعال باشد و کاربر عضو نباشد، پیام عضویت کانال را نشان داده
    و اجازه نمی‌دهد به handler اصلی برسد.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from app.services import settings_service as cfg
        from app.handlers.common import show_channel_membership_required

        session = data.get("session")
        user = data.get("user")
        is_admin = data.get("is_admin", False)
        
        if session is None or user is None or is_admin:
            # اگر admin است یا کاربر ثبت نشده، اجازه بدهید
            return await handler(event, data)
        
        # اجازه بده برای دکمه "بررسی عضویت" — کاربر باید بتواند پس از عضویت
        # وضعیت را با کلیک روی این دکمه چک کند
        if isinstance(event, CallbackQuery) and event.data == "check_membership":
            return await handler(event, data)
        
        # چک کن که عضویت الزامی فعال است؟
        channel_enabled = await cfg.get_bool(session, S_REQUIRED_CHANNEL_ENABLED, False)
        if not channel_enabled:
            return await handler(event, data)
        
        # دریافت شناسه کانال
        channel_id = await cfg.get(session, S_REQUIRED_CHANNEL_ID, None)
        if not channel_id:
            # اگر کانال تنظیم نشده، اجازه بدهید
            return await handler(event, data)
        
        # چک کن که کاربر عضو کانال است؟
        try:
            member = await data["bot"].get_chat_member(channel_id, user.id)
            # وضعیت‌های معتبر: member, creator, administrator, restricted
            if member.status in ["member", "creator", "administrator", "restricted"]:
                # عضو است
                return await handler(event, data)
        except Exception as e:
            logger.warning(f"Failed to check channel membership for user {user.id}: {e}")
            # اگر خطا شد، اجازه بدهید (بهتر از مسدود کردن)
            return await handler(event, data)
        
        # کاربر عضو نیست - ذخیره کن و اطلاع بدهید
        data["channel_membership_required"] = True
        data["required_channel_id"] = channel_id
        
        # نمایش پیام عضویت با دکمه لینک کانال و دکمه بررسی عضویت
        try:
            if isinstance(event, Message):
                await show_channel_membership_required(event, session, channel_id)
            elif isinstance(event, CallbackQuery):
                await event.answer()  # حذف وضعیت loading
                if event.message is not None:
                    await show_channel_membership_required(
                        event.message, session, channel_id
                    )
        except Exception as e:
            logger.warning(f"Failed to send membership required message: {e}")
        
        # خارج شو - handler را فراخوانی نکن
        return None
