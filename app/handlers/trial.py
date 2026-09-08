from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.handlers.delivery import send_config
from app.services import activity_service as activity
from app.services import provisioning
from app.services import settings_service as cfg
from app.services.vpn import VpnError
from app.texts import (
    BTN_TRIAL,
    MSG_PANEL_ERROR,
    MSG_TRIAL_ALREADY,
    MSG_TRIAL_DISABLED,
    MSG_TRIAL_WAIT,
    S_TRIAL_ENABLED,
)

logger = logging.getLogger(__name__)
router = Router(name="trial")


@router.message(F.text == BTN_TRIAL)
async def free_trial(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()  # Clear any existing state
    if not await cfg.get_bool(session, S_TRIAL_ENABLED, True):
        await message.answer(MSG_TRIAL_DISABLED)
        return

    if user.trial_used:
        await message.answer(MSG_TRIAL_ALREADY)
        return

    wait = await message.answer(MSG_TRIAL_WAIT)
    try:
        service = await provisioning.grant_trial(session, user)
    except VpnError as exc:
        logger.error("trial provisioning failed for %s: %s", user.id, exc)
        await wait.edit_text(MSG_PANEL_ERROR)
        return

    await wait.delete()
    await send_config(message.bot, message.chat.id, service, session)
    # لاگ فعالیت
    await activity.log_activity(session, user.id, activity.Actions.TRIAL)
