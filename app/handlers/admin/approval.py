"""تأیید/رد رسید توسط ادمین و تحویل خودکار کانفیگ."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Order, OrderKind, OrderStatus, Package, Service, User
from app.filters import IsAdmin
from app.handlers.delivery import send_config
from app.keyboards import inline
from app.services import points_service as pts
from app.services import provisioning
from app.services.vpn import VpnError
from app.states import AdminFlow
from app.texts import MSG_ORDER_REJECTED
from app.utils.formatting import money

logger = logging.getLogger(__name__)
router = Router(name="admin_approval")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


@router.callback_query(inline.ReceiptCB.filter(F.action == "approve"))
async def approve(
    call: CallbackQuery,
    callback_data: inline.ReceiptCB,
    session: AsyncSession,
    bot: Bot,
) -> None:
    order = await session.get(Order, callback_data.order_id)
    if order is None:
        await call.answer("سفارش یافت نشد.", show_alert=True)
        return
    if order.status == OrderStatus.APPROVED:
        await call.answer("قبلاً تأیید شده است.", show_alert=True)
        return
    if order.status != OrderStatus.AWAITING_APPROVAL:
        await call.answer("این سفارش قابل تأیید نیست.", show_alert=True)
        return

    buyer = await session.get(User, order.user_id)
    if buyer is None:
        await call.answer("کاربر یافت نشد.", show_alert=True)
        return

    await call.answer("در حال ساخت کانفیگ...")
    package = await session.get(Package, order.package_id) if order.package_id else None
    inbound_id = package.inbound_id if package else 1
    device_limit = package.device_limit if package else 0

    try:
        if order.kind == OrderKind.RENEW and order.renew_service_id:
            service = await session.get(Service, order.renew_service_id)
            if service is None:
                raise VpnError("service to renew not found")
            service = await provisioning.renew_service(
                session,
                service=service,
                add_days=order.days,
                add_traffic_mb=order.traffic_mb,
                title=order.title,
            )
        else:
            service = await provisioning.create_service(
                session,
                user=buyer,
                days=order.days,
                traffic_mb=order.traffic_mb,
                inbound_id=inbound_id,
                title=order.title,
                device_limit=device_limit,
                order=order,
            )
    except VpnError as exc:
        logger.error("provisioning failed for order %s: %s", order.id, exc)
        await call.message.reply(
            f"❌ ساخت کانفیگ برای سفارش #{order.id} ناموفق بود:\n<code>{exc}</code>\n"
            "پس از رفع مشکل دوباره «تأیید» را بزنید."
        )
        return

    order.status = OrderStatus.APPROVED
    order.admin_id = call.from_user.id
    order.decided_at = datetime.now(timezone.utc)
    await session.commit()

    # تحویل کانفیگ به کاربر
    try:
        await bot.send_message(buyer.id, "🎉 پرداخت شما تأیید شد!")
        await send_config(bot, buyer.id, service, session)
    except Exception:  # noqa: BLE001
        logger.exception("failed delivering config to user %s", buyer.id)

    # پاداش معرف در اولین خرید
    reward = await pts.reward_referrer_on_first_purchase(session, buyer)
    if reward is not None:
        referrer, points = reward
        try:
            await bot.send_message(
                referrer.id,
                f"🎁 یکی از دوستان دعوت‌شده شما خرید کرد!\n"
                f"<b>{points}</b> امتیاز به شما اضافه شد.",
            )
        except Exception:  # noqa: BLE001
            logger.info("could not notify referrer %s", referrer.id)

    await _mark_reviewed(call, f"✅ تأیید شد و کانفیگ ارسال گردید. (توسط {call.from_user.id})")


@router.callback_query(inline.ReceiptCB.filter(F.action == "reject"))
async def reject_start(
    call: CallbackQuery,
    callback_data: inline.ReceiptCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    order = await session.get(Order, callback_data.order_id)
    if order is None or order.status != OrderStatus.AWAITING_APPROVAL:
        await call.answer("این سفارش قابل رد نیست.", show_alert=True)
        return
    await state.set_state(AdminFlow.reject_note)
    await state.update_data(order_id=order.id, review_chat=call.message.chat.id,
                            review_msg=call.message.message_id)
    await call.message.reply(
        "علت رد را بنویسید (برای کاربر ارسال می‌شود).\n"
        "برای رد بدون توضیح «-» بفرستید."
    )
    await call.answer()


@router.message(AdminFlow.reject_note)
async def reject_finish(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()
    order = await session.get(Order, data.get("order_id", 0))
    if order is None:
        await message.answer("سفارش یافت نشد.")
        return

    note = message.text.strip()
    order.status = OrderStatus.REJECTED
    order.admin_id = message.from_user.id
    order.admin_note = None if note == "-" else note
    order.decided_at = datetime.now(timezone.utc)
    await session.commit()

    note_line = f"دلیل: {order.admin_note}" if order.admin_note else "دلیل ذکر نشده."
    try:
        await bot.send_message(
            order.user_id,
            MSG_ORDER_REJECTED.format(order_id=order.id, note=note_line),
        )
    except Exception:  # noqa: BLE001
        logger.info("could not notify user %s about rejection", order.user_id)

    await message.answer(f"❌ سفارش #{order.id} رد شد و به کاربر اطلاع داده شد.")


async def _mark_reviewed(call: CallbackQuery, note: str) -> None:
    """کپشن پیام رسید را به‌روز و دکمه‌ها را حذف می‌کند."""
    base = call.message.caption or call.message.text or ""
    new_text = f"{base}\n\n{note}"
    try:
        if call.message.caption is not None:
            await call.message.edit_caption(caption=new_text, reply_markup=None)
        else:
            await call.message.edit_text(new_text, reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
