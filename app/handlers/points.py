from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Service, ServiceStatus, User
from app.handlers.delivery import send_config
from app.keyboards import inline
from app.services import activity_service as activity
from app.services import points_service as pts
from app.services import provisioning
from app.services import settings_service as cfg
from app.services.vpn import VpnError
from app.texts import (
    BTN_INVITE,
    BTN_POINTS,
    MSG_PANEL_ERROR,
    S_INVITE_TEXT,
    S_POINTS_PER_DAY,
    S_POINTS_TEXT,
    S_REDEEM_INBOUND,
    S_REFERRAL_POINTS,
)
from app.utils.formatting import fa_digits, render

logger = logging.getLogger(__name__)
router = Router(name="points")


@router.message(F.text == BTN_POINTS)
async def my_points(message: Message, session: AsyncSession, user: User) -> None:
    per_day = await cfg.get_int(session, S_POINTS_PER_DAY, 10)
    days = await pts.points_to_days(session, user.points)
    text = render(
        await cfg.get(session, S_POINTS_TEXT),
        points=fa_digits(user.points),
        per_day=fa_digits(per_day),
        days=fa_digits(days),
    )
    await message.answer(text, reply_markup=inline.points_kb(days))
    # لاگ فعالیت
    await activity.log_activity(session, user.id, activity.Actions.VIEW_POINTS)


@router.callback_query(inline.PointsCB.filter(F.action == "redeem"))
async def redeem_points(
    call: CallbackQuery,
    callback_data: inline.PointsCB,
    session: AsyncSession,
    user: User,
) -> None:
    days = callback_data.days
    if days <= 0:
        await call.answer("امتیاز کافی ندارید.", show_alert=True)
        return

    await session.refresh(user)
    ok = await pts.spend_points_for_days(session, user, days)
    if not ok:
        await call.answer("امتیاز کافی ندارید.", show_alert=True)
        return

    await call.message.edit_text("⏳ در حال ساخت اشتراک هدیه...")
    inbound_id = await cfg.get_int(session, S_REDEEM_INBOUND, 1)
    try:
        service = await provisioning.create_service(
            session,
            user=user,
            days=days,
            traffic_mb=0,
            inbound_id=inbound_id,
            title=f"اشتراک هدیه {fa_digits(days)} روزه",
            device_limit=1,
        )
    except VpnError as exc:
        logger.error("redeem provisioning failed for %s: %s", user.id, exc)
        # برگرداندن امتیاز
        await pts.add_points(session, user, callback_data.days, "redeem_refund")
        await call.message.edit_text(MSG_PANEL_ERROR)
        return

    await call.message.edit_text(
        f"🎉 اشتراک هدیه {fa_digits(days)} روزه ساخته شد!"
    )
    await send_config(call.bot, call.message.chat.id, service, session)
    await call.answer()
    # لاگ فعالیت
    await activity.log_activity(
        session, user.id, activity.Actions.REDEEM_POINTS,
        {"days": days, "points_spent": callback_data.days}
    )


@router.message(F.text == BTN_INVITE)
async def invite(message: Message, session: AsyncSession, user: User) -> None:
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user.id}"
    points = await cfg.get_int(session, S_REFERRAL_POINTS, 10)
    invited = await pts.count_successful_referrals(session, user.id)

    text = render(
        await cfg.get(session, S_INVITE_TEXT),
        points=fa_digits(points),
        link=link,
        invited=fa_digits(invited),
    )
    share = "با این ربات به‌راحتی اشتراک تهیه کن! 🌐"
    await message.answer(
        text,
        reply_markup=inline.invite_kb(link, share),
        disable_web_page_preview=True,
    )
    # لاگ فعالیت
    await activity.log_activity(
        session, user.id, activity.Actions.INVITE,
        {"invited_count": invited}
    )
