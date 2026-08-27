from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import get_settings


class IsAdmin(BaseFilter):
    """فقط برای شناسه‌های تعریف‌شده در ADMIN_IDS."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        return user is not None and get_settings().is_admin(user.id)
