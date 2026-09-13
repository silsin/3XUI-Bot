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
