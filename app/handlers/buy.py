from __future__ import annotations

import json
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    Duration,
    Order,
    OrderKind,
    OrderStatus,
    Package,
    Service,
    ServiceStatus,
    User,
)
from app.keyboards import inline
from app.keyboards import reply
from app.services import activity_service as activity
from app.services import settings_service as cfg
from app.states import BuyFlow
from app.texts import (
    BTN_BUY,
    BTN_RENEW,
    MSG_CANCELLED,
    MSG_CHOOSE_DURATION,
    MSG_CHOOSE_PACKAGE,
    MSG_NO_DURATION,
    MSG_NO_PACKAGE,
    MSG_NO_SERVICES,
    MSG_RECEIPT_ASK,
    MSG_RECEIPT_INVALID,
    MSG_RECEIPT_SENT,
    S_BUY_INSTRUCTION,
    S_CARD_HOLDER,
    S_CARD_NUMBER,
)
from app.utils.formatting import days_left_text, money, render, traffic

logger = logging.getLogger(__name__)
router = Router(name="buy")


async def _active_durations(session: AsyncSession) -> list[Duration]:
    return list(
        (
            await session.execute(
                select(Duration)
                .where(Duration.is_active.is_(True))
                .order_by(Duration.sort_order, Duration.days)
            )
        ).scalars().all()
    )


async def _active_packages(session: AsyncSession, duration_id: int) -> list[Package]:
    return list(
        (
            await session.execute(
                select(Package)
                .where(
                    Package.duration_id == duration_id,
                    Package.is_active.is_(True),
                )
                .order_by(Package.sort_order, Package.price)
            )
        ).scalars().all()
    )


# ---------- ورود به جریان خرید ----------


@router.message(F.text == BTN_BUY)
async def start_buy(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    durations = await _active_durations(session)
    if not durations:
        await message.answer(MSG_NO_DURATION)
        return
    await message.answer(
        MSG_CHOOSE_DURATION, reply_markup=inline.durations_kb(durations)
    )
    # لاگ فعالیت
    await activity.log_activity(session, message.from_user.id, activity.Actions.VIEW_PLANS)


@router.message(F.text == BTN_RENEW)
async def start_renew(message: Message, session: AsyncSession, user: User) -> None:
    services = list(
        (
            await session.execute(
                select(Service)
                .where(Service.user_id == user.id)
                .order_by(Service.created_at.desc())
            )
        ).scalars().all()
    )
    if not services:
        await message.answer(MSG_NO_SERVICES)
        return
    await message.answer(
        "کدام سرویس را می‌خواهید تمدید کنید؟",
        reply_markup=inline.services_kb(services),
    )
    # لاگ فعالیت
    await activity.log_activity(session, user.id, activity.Actions.INITIATE_BUY, {"type": "renew"})


# ---------- ناوبری اینلاین ----------


@router.callback_query(inline.BuyCB.filter(F.action == "durations"))
async def show_durations(
    call: CallbackQuery, callback_data: inline.BuyCB, session: AsyncSession
) -> None:
    durations = await _active_durations(session)
    if not durations:
        await call.message.edit_text(MSG_NO_DURATION)
        await call.answer()
        return
    await call.message.edit_text(
        MSG_CHOOSE_DURATION,
        reply_markup=inline.durations_kb(durations, callback_data.service_id),
    )
    await call.answer()
    # لاگ فعالیت
    await activity.log_activity(session, call.from_user.id, activity.Actions.VIEW_DURATIONS)


@router.callback_query(inline.BuyCB.filter(F.action == "packages"))
async def show_packages(
    call: CallbackQuery, callback_data: inline.BuyCB, session: AsyncSession
) -> None:
    duration = await session.get(Duration, callback_data.duration_id)
    packages = await _active_packages(session, callback_data.duration_id)
    if duration is None or not packages:
        await call.answer(MSG_NO_PACKAGE, show_alert=True)
        return
    await call.message.edit_text(
        MSG_CHOOSE_PACKAGE.format(duration=duration.title),
        reply_markup=inline.packages_kb(
            packages, callback_data.duration_id, callback_data.service_id
        ),
    )
    await call.answer()
    # لاگ فعالیت
    await activity.log_activity(
        session, call.from_user.id, activity.Actions.VIEW_PACKAGES,
        {"duration_id": callback_data.duration_id, "duration_title": duration.title}
    )


@router.callback_query(inline.BuyCB.filter(F.action == "checkout"))
async def show_checkout(
    call: CallbackQuery, callback_data: inline.BuyCB, session: AsyncSession
) -> None:
    package = await session.get(Package, callback_data.package_id)
    duration = await session.get(Duration, callback_data.duration_id)
    if package is None or duration is None:
        await call.answer(MSG_NO_PACKAGE, show_alert=True)
        return

    summary = inline.package_summary(package, duration)
    if callback_data.service_id:
        summary = "♻️ <b>تمدید سرویس</b>\n\n" + summary
    await call.message.edit_text(
        summary,
        reply_markup=inline.checkout_kb(
            callback_data.duration_id,
            callback_data.package_id,
            callback_data.service_id,
        ),
    )
    await call.answer()


@router.callback_query(inline.BuyCB.filter(F.action == "cancel"))
async def cancel_buy(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(MSG_CANCELLED)
    await call.answer()


# ---------- ساخت سفارش و درخواست رسید ----------


@router.callback_query(inline.BuyCB.filter(F.action == "pay"))
async def create_order(
    call: CallbackQuery,
    callback_data: inline.BuyCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    package = await session.get(Package, callback_data.package_id)
    duration = await session.get(Duration, callback_data.duration_id)
    if package is None or duration is None:
        await call.answer(MSG_NO_PACKAGE, show_alert=True)
        return

    renew_service_id = callback_data.service_id or None
    if renew_service_id:
        svc = await session.get(Service, renew_service_id)
        if svc is None or svc.user_id != user.id:
            await call.answer("سرویس یافت نشد.", show_alert=True)
            return

    order = Order(
        user_id=user.id,
        package_id=package.id,
        renew_service_id=renew_service_id,
        kind=OrderKind.RENEW if renew_service_id else OrderKind.NEW,
        status=OrderStatus.AWAITING_RECEIPT,
        amount=package.price,
        days=duration.days,
        traffic_mb=package.traffic_mb,
        title=f"{package.title} — {duration.title}",
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    card_number = await cfg.get(session, S_CARD_NUMBER)
    instruction = render(
        await cfg.get(session, S_BUY_INSTRUCTION),
        amount=money(package.price),
        card_number=card_number,
        card_holder=await cfg.get(session, S_CARD_HOLDER),
    )
    await call.message.edit_text(
        instruction,
        reply_markup=inline.payment_kb(order.id, card_number, package.price),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data.startswith("receipt:cancel:"))
async def receipt_cancel(call: CallbackQuery, session: AsyncSession) -> None:
    order_id = int(call.data.split(":")[2])
    order = await session.get(Order, order_id)
    if order and order.status == OrderStatus.AWAITING_RECEIPT:
        order.status = OrderStatus.CANCELLED
        await session.commit()
    await call.message.edit_text(MSG_CANCELLED)
    await call.answer()


@router.callback_query(F.data.startswith("receipt:start:"))
async def receipt_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    order_id = int(call.data.split(":")[2])
    order = await session.get(Order, order_id)
    if order is None or order.user_id != user.id:
        await call.answer("سفارش یافت نشد.", show_alert=True)
        return
    if order.status != OrderStatus.AWAITING_RECEIPT:
        await call.answer("این سفارش دیگر در انتظار رسید نیست.", show_alert=True)
        return

    await state.set_state(BuyFlow.waiting_receipt)
    await state.update_data(order_id=order_id)
    await call.message.answer(MSG_RECEIPT_ASK)
    await call.answer()


@router.message(BuyFlow.waiting_receipt, F.photo | F.document)
async def receive_receipt(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    data = await state.get_data()
    order = await session.get(Order, data.get("order_id", 0))
    if order is None or order.user_id != user.id:
        await state.clear()
        await message.answer("سفارش یافت نشد.", reply_markup=reply.main_menu())
        return

    if message.photo:
        order.receipt_file_id = message.photo[-1].file_id
        order.receipt_is_document = False
    else:
        order.receipt_file_id = message.document.file_id
        order.receipt_is_document = True
    order.status = OrderStatus.AWAITING_APPROVAL
    await session.commit()
    await state.clear()

    await message.answer(
        MSG_RECEIPT_SENT, reply_markup=reply.main_menu(get_settings().is_admin(user.id))
    )
    await _notify_admin(bot, session, order, user, message)


@router.message(BuyFlow.waiting_receipt)
async def receipt_invalid(message: Message) -> None:
    await message.answer(MSG_RECEIPT_INVALID)


async def _notify_admin(
    bot: Bot, session: AsyncSession, order: Order, user: User, message: Message
) -> None:
    targets = get_settings().receipts_targets
    if not targets:
        logger.warning("no receipts target configured; order %s", order.id)
        return

    uname = f"@{user.username}" if user.username else "—"
    kind = "تمدید ♻️" if order.kind == OrderKind.RENEW else "خرید جدید 🛒"
    caption = (
        f"🧾 <b>سفارش #{order.id}</b> ({kind})\n\n"
        f"👤 کاربر: {user.first_name or ''} ({uname})\n"
        f"🆔 <code>{user.id}</code>\n"
        f"📦 {order.title}\n"
        f"⏱ {order.days} روز | 📊 {traffic(order.traffic_mb)}\n"
        f"💰 مبلغ: <b>{money(order.amount)} تومان</b>"
    )
    markup = inline.receipt_review_kb(order.id)
    sent: list[list[int]] = []
    for target in targets:
        try:
            if order.receipt_is_document:
                msg = await bot.send_document(
                    target, order.receipt_file_id, caption=caption, reply_markup=markup
                )
            else:
                msg = await bot.send_photo(
                    target, order.receipt_file_id, caption=caption, reply_markup=markup
                )
            sent.append([msg.chat.id, msg.message_id])
        except Exception:  # noqa: BLE001 — یک ادمین ممکن است ربات را استارت نکرده باشد
            logger.exception("failed to notify admin %s for order %s", target, order.id)

    order.notify_msgs = json.dumps(sent)
    await session.commit()
