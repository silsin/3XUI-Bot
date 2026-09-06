from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import activity_service as activity
from app.services import settings_service as cfg
from app.texts import BTN_GUIDE, BTN_SUPPORT, S_GUIDE_TEXT, S_SUPPORT_TEXT

router = Router(name="misc")


@router.message(F.text == BTN_GUIDE)
async def guide(message: Message, session: AsyncSession) -> None:
    await message.answer(
        await cfg.get(session, S_GUIDE_TEXT), disable_web_page_preview=True
    )
    # لاگ فعالیت
    await activity.log_activity(session, message.from_user.id, activity.Actions.GUIDE)


@router.message(F.text == BTN_SUPPORT)
async def support(message: Message, session: AsyncSession) -> None:
    await message.answer(
        await cfg.get(session, S_SUPPORT_TEXT), disable_web_page_preview=True
    )
    # لاگ فعالیت
    await activity.log_activity(session, message.from_user.id, activity.Actions.SUPPORT)
