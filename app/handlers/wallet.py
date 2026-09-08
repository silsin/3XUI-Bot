"""تقسیم سرویس و انتقال به کاربر دیگر (ساده‌شده).

جریان:
1. کاربر روی دکمه "تقسیم این کانفیگ" در سرویس detail زد
2. دکمه‌های اندازه نمایش داده می‌شوند
3. کاربر اندازه را انتخاب می‌کند → سؤال: برای خودم یا دیگری؟
4. برای دیگری → ورود @username → تأیید
5. برای خودم → تأیید مستقیم
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Service, User
from app.handlers.delivery import send_config
from app.keyboards import inline
from app.services import activity_service as activity
from app.services import wallet_service as wallet
from app.states import WalletFlow
from app.texts import (
    MSG_CANCELLED,
    MSG_WALLET_CONFIRM_OTHER,
    MSG_WALLET_CONFIRM_SELF,
    MSG_WALLET_INTRO,
    MSG_WALLET_PROCESSING,
    MSG_WALLET_RECIPIENT_NOT_FOUND,
    MSG_WALLET_SELECT_TYPE,
    MSG_WALLET_SUCCESS_OTHER,
    MSG_WALLET_SUCCESS_SELF,
)
from app.utils.formatting import days_left_text, fa_digits, jalali_date, traffic

logger = logging.getLogger(__name__)
router = Router(name="wallet")


# ══════════════════════════════════════════════════════════════════
#  Step 1: Entry point (from service detail view)
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "start_split"))
async def start_split(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
) -> None:
    """کاربر روی دکمه تقسیم سرویس زد."""
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    avail = wallet.available_mb(service)
    text = MSG_WALLET_SELECT_TYPE.format(
        title=service.title,
        available=traffic(avail),
        expires=jalali_date(service.expires_at),
    )
    await call.message.edit_text(
        text,
        reply_markup=inline.wallet_size_kb(service.id, avail),
    )
    await call.answer()
    await activity.log_activity(session, user.id, "wallet_start_split", {"service_id": service.id})


# ══════════════════════════════════════════════════════════════════
#  Step 2: Select size → ask for self or other
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "select_size"))
async def select_size(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
) -> None:
    """کاربر اندازه را انتخاب کرد — اکنون انتخاب می‌کند برای خودم یا دیگری."""
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    allocated_mb = callback_data.allocated_mb
    err = await wallet.validate_split(session, service, allocated_mb, user.id)
    if err:
        await call.answer(err, show_alert=True)
        return

    # سؤال: برای خودم یا دیگری؟
    await call.message.edit_text(
        "برای چه کسی این کانفیگ را ایجاد کنم؟",
        reply_markup=inline.wallet_recipient_kb(service.id, allocated_mb),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════
#  Step 4A: For self — direct confirmation
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "confirm_self"))
async def confirm_for_self(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    """کاربر تأیید کرد برای خودش."""
    await state.clear()

    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    allocated_mb = callback_data.allocated_mb
    avail = wallet.available_mb(service)
    remainder = avail - allocated_mb

    text = MSG_WALLET_CONFIRM_SELF.format(
        parent_title=service.title,
        allocated=traffic(allocated_mb),
        remainder=traffic(remainder),
        expires=jalali_date(service.expires_at),
    )

    await call.message.edit_text(
        text,
        reply_markup=inline.wallet_confirm_kb(
            service.id, allocated_mb, recipient_username=None
        ),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════
#  Step 4B: For other — ask for username
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "ask_recipient"))
async def ask_recipient_username(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    state: FSMContext,
) -> None:
    """کاربر برای دیگری انتخاب کرد — منتظر ورود username."""
    await state.set_state(WalletFlow.confirming)
    await state.update_data(
        service_id=callback_data.service_id,
        allocated_mb=callback_data.allocated_mb,
        for_other=True,
    )
    await call.message.edit_text(
        "👤 <b>نام‌کاربری گیرنده را وارد کنید</b>\n\n"
        "مثال: <code>john</code> یا <code>@john</code>"
    )
    await call.answer()


@router.message(WalletFlow.confirming)
async def receive_recipient_username(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    """دریافت username و نمایش تأیید."""
    data = await state.get_data()
    service_id = data.get("service_id", 0)
    allocated_mb = data.get("allocated_mb", 0)
    for_other = data.get("for_other", False)

    if not for_other:
        # این برای خودم است (تأیید مستقیم)
        await state.clear()
        service = await session.get(Service, service_id)
        if service is None or service.user_id != user.id:
            await message.answer("سرویس یافت نشد.")
            return
        await _execute_split_for_self(
            message, session, user, service, allocated_mb, bot
        )
        return

    # برای دیگری — جستجوی username
    recipient_username = (message.text or "").strip()
    recipient = await wallet.get_user_by_username(session, recipient_username)
    if recipient is None:
        await message.answer(MSG_WALLET_RECIPIENT_NOT_FOUND)
        return

    if recipient.id == user.id:
        await message.answer(
            "❌ نمی‌توانید برای خودتان انتقال دهید. "
            "از گزینه «ساخت کانفیگ برای خودم» استفاده کنید."
        )
        return

    await state.clear()
    service = await session.get(Service, service_id)
    if service is None or service.user_id != user.id:
        await message.answer("سرویس یافت نشد.")
        return

    avail = wallet.available_mb(service)
    remainder = avail - allocated_mb
    r_name = recipient.first_name or recipient_username

    text = MSG_WALLET_CONFIRM_OTHER.format(
        parent_title=service.title,
        allocated=traffic(allocated_mb),
        remainder=traffic(remainder),
        expires=jalali_date(service.expires_at),
        recipient_name=r_name,
        recipient_id=recipient.id,
    )

    await message.answer(
        text,
        reply_markup=inline.wallet_confirm_kb(
            service.id, allocated_mb, recipient_username=recipient_username, 
            recipient_id=recipient.id
        ),
    )


# ══════════════════════════════════════════════════════════════════
#  Final: Execute split
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "execute"))
async def execute_split(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    """اجرای تقسیم و ارسال کانفیگ."""
    await state.clear()

    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    allocated_mb = callback_data.allocated_mb
    recipient_id = callback_data.recipient_id

    if recipient_id == 0:
        # برای خودم
        await _execute_split_for_self(
            call.message, session, user, service, allocated_mb, bot
        )
    else:
        # برای دیگری
        recipient = await session.get(User, recipient_id)
        if recipient is None:
            await call.message.edit_text("❌ کاربر گیرنده یافت نشد.")
            await call.answer()
            return

        await _execute_split_for_other(
            call.message, session, user, recipient, service, allocated_mb, bot
        )

    await call.answer()


# ══════════════════════════════════════════════════════════════════
#  Helpers: Execute split logic
# ══════════════════════════════════════════════════════════════════

async def _execute_split_for_self(
    message_or_call,
    session: AsyncSession,
    user: User,
    service: Service,
    allocated_mb: int,
    bot: Bot,
) -> None:
    """اجرای تقسیم برای خود کاربر."""
    try:
        await message_or_call.edit_text(MSG_WALLET_PROCESSING)
    except AttributeError:
        await message_or_call.answer(MSG_WALLET_PROCESSING)

    try:
        child = await wallet.do_split(
            session,
            parent=service,
            allocated_mb=allocated_mb,
            recipient=user,
            title=f"کانفیگ {traffic(allocated_mb)}",
            owner_id=user.id,
        )
    except wallet.SplitError as exc:
        await message_or_call.edit_text(f"❌ {exc}")
        return

    await session.refresh(service)
    remainder = service.traffic_mb

    try:
        await message_or_call.edit_text(
            MSG_WALLET_SUCCESS_SELF.format(
                allocated=traffic(allocated_mb),
                remainder=traffic(remainder),
            )
        )
    except AttributeError:
        await message_or_call.answer(
            MSG_WALLET_SUCCESS_SELF.format(
                allocated=traffic(allocated_mb),
                remainder=traffic(remainder),
            )
        )

    await send_config(bot, user.id, child, session)
    await activity.log_activity(
        session, user.id, "wallet_split_self",
        {"parent_id": service.id, "child_id": child.id, "allocated_mb": allocated_mb},
    )


async def _execute_split_for_other(
    message_or_call,
    session: AsyncSession,
    sender: User,
    recipient: User,
    service: Service,
    allocated_mb: int,
    bot: Bot,
) -> None:
    """اجرای تقسیم برای کاربر دیگر."""
    try:
        await message_or_call.edit_text(MSG_WALLET_PROCESSING)
    except AttributeError:
        await message_or_call.answer(MSG_WALLET_PROCESSING)

    try:
        child = await wallet.do_split(
            session,
            parent=service,
            allocated_mb=allocated_mb,
            recipient=recipient,
            title=f"کانفیگ {traffic(allocated_mb)}",
            owner_id=sender.id,
        )
    except wallet.SplitError as exc:
        await message_or_call.edit_text(f"❌ {exc}")
        return

    await session.refresh(service)
    remainder = service.traffic_mb
    r_name = recipient.first_name or recipient.username or str(recipient.id)

    try:
        await message_or_call.edit_text(
            MSG_WALLET_SUCCESS_OTHER.format(
                allocated=traffic(allocated_mb),
                recipient_name=r_name,
                remainder=traffic(remainder),
            )
        )
    except AttributeError:
        await message_or_call.answer(
            MSG_WALLET_SUCCESS_OTHER.format(
                allocated=traffic(allocated_mb),
                recipient_name=r_name,
                remainder=traffic(remainder),
            )
        )

    # ارسال کانفیگ به گیرنده
    try:
        await bot.send_message(
            recipient.id,
            f"🎁 یک کانفیگ جدید ({traffic(allocated_mb)}) "
            f"از طرف {sender.first_name or sender.username or 'یک کاربر'} برای شما ساخته شد!",
        )
        await send_config(bot, recipient.id, child, session)
    except Exception:
        logger.exception("failed delivering split config to user %s", recipient.id)

    await activity.log_activity(
        session, sender.id, "wallet_split_other",
        {
            "parent_id": service.id,
            "child_id": child.id,
            "allocated_mb": allocated_mb,
            "recipient_id": recipient.id,
        },
    )


# ══════════════════════════════════════════════════════════════════
#  Cancel from anywhere
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "cancel"))
async def cancel_wallet(call: CallbackQuery, state: FSMContext) -> None:
    """لغو جریان."""
    await state.clear()
    await call.message.edit_text(MSG_CANCELLED)
    await call.answer()
