from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.keyboards import reply
from app.services import activity_service as activity
from app.services import settings_service as cfg
from app.utils.formatting import render
from app.texts import (
    MSG_CANCELLED,
    MSG_UNKNOWN,
    S_WELCOME_IMAGE,
    S_WELCOME_TEXT,
)

logger = logging.getLogger(__name__)
router = Router(name="common")
fallback_router = Router(name="fallback")


async def _apply_referral(
    session: AsyncSession, user: User, command: CommandObject | None
) -> None:
    """اگر کاربر تازه است و با لینک دعوت آمده، معرف را ثبت می‌کند."""
    if user.referrer_id is not None or command is None or not command.args:
        return
    arg = command.args.strip()
    if not arg.startswith("ref_"):
        return
    try:
        referrer_id = int(arg[4:])
    except ValueError:
        return
    if referrer_id == user.id:
        return
    referrer = await session.get(User, referrer_id)
    if referrer is not None:
        user.referrer_id = referrer_id
        await session.commit()
        logger.info("user %s referred by %s", user.id, referrer_id)


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    is_admin: bool,
    state: FSMContext,
) -> None:
    await state.clear()
    await _apply_referral(session, user, command)

    text = render(
        await cfg.get(session, S_WELCOME_TEXT), name=user.first_name or "کاربر"
    )
    image = await cfg.get(session, S_WELCOME_IMAGE)
    markup = reply.main_menu(is_admin=is_admin)

    if image:
        try:
            # کپشن تلگرام حداکثر ۱۰۲۴ کاراکتر است
            if len(text) <= 1024:
                await message.answer_photo(image, caption=text, reply_markup=markup)
            else:
                await message.answer_photo(image)
                await message.answer(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            # file_id مختص هر ربات است؛ اگر توکن ربات عوض شده باشد نامعتبر می‌شود
            logger.warning("welcome image file_id invalid, clearing it")
            await cfg.set_value(session, S_WELCOME_IMAGE, "")

    await message.answer(text, reply_markup=markup)
    # لاگ فعالیت
    await activity.log_activity(session, user.id, activity.Actions.START)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, is_admin: bool) -> None:
    await state.clear()
    await message.answer(MSG_CANCELLED, reply_markup=reply.main_menu(is_admin))


@router.message(Command("menu"))
async def cmd_menu(message: Message, is_admin: bool, session: AsyncSession) -> None:
    await message.answer("منوی اصلی 👇", reply_markup=reply.main_menu(is_admin))
    # لاگ فعالیت
    await activity.log_activity(session, message.from_user.id, activity.Actions.MENU)


@fallback_router.message(F.text)
async def unknown(message: Message, is_admin: bool) -> None:
    """آخرین هندلر: پیام‌های متنی ناشناخته."""
    await message.answer(MSG_UNKNOWN, reply_markup=reply.main_menu(is_admin))
