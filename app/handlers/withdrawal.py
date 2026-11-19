"""درخواست برداشت از کیف پول — سمت کاربر."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.services import activity_service as activity
from app.services import withdrawal_service as wd
from app.services.wallet_balance_service import WalletBalanceService
from app.states import WithdrawalFlow
from app.utils.formatting import money

logger = logging.getLogger(__name__)
router = Router(name="withdrawal")

_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _cancel_kb():
    b = InlineKeyboardBuilder()
    b.button(text="❌ لغو", callback_data="wd:abort")
    return b.as_markup()


@router.callback_query(F.data == "wd:start")
async def wd_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    wallets = WalletBalanceService(session)
    if not await wallets.is_enabled(user.id):
        await call.answer("⚠️ کیف پول غیرفعال است.", show_alert=True)
        return
    if await wd.has_open_request(session, user.id):
        await call.answer(
            "شما یک درخواست برداشت در حال بررسی دارید.", show_alert=True
        )
        return
    balance = await wallets.get_balance(user.id)
    if balance < wd.MIN_WITHDRAWAL:
        await call.answer(
            f"حداقل مبلغ برداشت {wd.MIN_WITHDRAWAL:,} تومان است.", show_alert=True
        )
        return
    await state.set_state(WithdrawalFlow.waiting_amount)
    await call.message.answer(
        f"<b>💸 درخواست برداشت</b>\n\n"
        f"موجودی شما: <b>{money(balance)} تومان</b>\n"
        f"مبلغ مورد نظر برای برداشت را (به تومان) وارد کنید.\n"
        f"حداقل: {money(wd.MIN_WITHDRAWAL)} تومان",
        reply_markup=_cancel_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "wd:abort")
async def wd_abort(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("❌ درخواست برداشت لغو شد.")
    await call.answer()


@router.message(WithdrawalFlow.waiting_amount, F.text)
async def wd_amount(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    raw = message.text.translate(_FA).replace(",", "").replace("٬", "").strip()
    if not raw.isdigit():
        await message.answer("❌ لطفاً فقط عدد وارد کنید.", reply_markup=_cancel_kb())
        return
    amount = int(raw)
    balance = await WalletBalanceService(session).get_balance(user.id)
    err = wd.validate_amount(amount, balance)
    if err:
        await message.answer(f"❌ {err}", reply_markup=_cancel_kb())
        return
    await state.update_data(amount=amount)
    await state.set_state(WithdrawalFlow.waiting_card)
    await message.answer(
        "شماره کارت ۱۶ رقمی مقصد (برای واریز) را وارد کنید:",
        reply_markup=_cancel_kb(),
    )


@router.message(WithdrawalFlow.waiting_card, F.text)
async def wd_card(message: Message, state: FSMContext) -> None:
    card = wd.parse_card(message.text)
    if not card:
        await message.answer(
            "❌ شماره کارت باید ۱۶ رقم باشد.", reply_markup=_cancel_kb()
        )
        return
    await state.update_data(card=card)
    await state.set_state(WithdrawalFlow.waiting_holder)
    await message.answer(
        "نام صاحب کارت را وارد کنید:", reply_markup=_cancel_kb()
    )


@router.message(WithdrawalFlow.waiting_holder, F.text)
async def wd_holder(message: Message, state: FSMContext) -> None:
    holder = message.text.strip()
    if not (2 <= len(holder) <= 100):
        await message.answer("❌ نام نامعتبر است.", reply_markup=_cancel_kb())
        return
    await state.update_data(holder=holder)
    await state.set_state(WithdrawalFlow.confirming)
    data = await state.get_data()
    b = InlineKeyboardBuilder()
    b.button(text="✅ تایید و ثبت درخواست", callback_data="wd:confirm")
    b.button(text="❌ لغو", callback_data="wd:abort")
    b.adjust(1)
    await message.answer(
        f"<b>خلاصه درخواست برداشت</b>\n\n"
        f"💰 مبلغ: <b>{money(data['amount'])} تومان</b>\n"
        f"💳 کارت: <code>{data['card']}</code>\n"
        f"👤 صاحب کارت: {holder}\n\n"
        f"با ثبت درخواست، مبلغ فوراً از کیف پول شما کسر می‌شود و در صورت رد "
        f"درخواست برگردانده خواهد شد.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "wd:confirm", WithdrawalFlow.confirming)
async def wd_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    try:
        req = await wd.create_request(
            session, user.id, data["amount"], data["card"], data["holder"]
        )
        await session.commit()
    except (wd.WithdrawalError, KeyError) as exc:
        await session.rollback()
        await state.clear()
        await call.message.edit_text(f"❌ {exc}")
        await call.answer()
        return
    await state.clear()

    b = InlineKeyboardBuilder()
    b.button(text="🚫 لغو درخواست", callback_data=f"wd:cancel:{req.id}")
    await call.message.edit_text(
        f"✅ <b>درخواست برداشت ثبت شد</b>\n\n"
        f"شماره درخواست: #{req.id}\n"
        f"مبلغ: {money(req.amount)} تومان (از کیف پول کسر شد)\n\n"
        f"پس از تایید ادمین و واریز، رسید برای شما ارسال می‌شود.",
        reply_markup=b.as_markup(),
    )
    await call.answer()

    # اطلاع به ادمین‌ها
    from app.handlers.admin.withdrawals import admin_request_markup, admin_request_text

    sent: list[list[int]] = []
    text = admin_request_text(req, user)
    for target in get_settings().receipts_targets:
        try:
            m = await call.bot.send_message(
                target, text, reply_markup=admin_request_markup(req.id)
            )
            sent.append([m.chat.id, m.message_id])
        except Exception:
            logger.exception("failed to notify admin %s for withdrawal %s", target, req.id)
    req.notify_msgs = json.dumps(sent)
    await session.commit()
    await activity.log_activity(
        session, user.id, "wallet_withdrawal_request",
        {"amount": req.amount, "request_id": req.id},
    )


@router.callback_query(F.data.startswith("wd:cancel:"))
async def wd_cancel(
    call: CallbackQuery, session: AsyncSession, user: User
) -> None:
    try:
        rid = int(call.data.split(":")[2])
    except (ValueError, IndexError):
        await call.answer("❌ نامعتبر", show_alert=True)
        return
    try:
        req = await wd.cancel_by_user(session, rid, user.id)
        await session.commit()
    except wd.WithdrawalError as exc:
        await session.rollback()
        await call.answer(f"❌ {exc}", show_alert=True)
        return
    await call.message.edit_text(
        f"🚫 درخواست برداشت #{req.id} لغو شد و {money(req.amount)} تومان "
        f"به کیف پول شما برگشت."
    )
    await call.answer()
    for chat_id, msg_id in json.loads(req.notify_msgs or "[]"):
        try:
            await call.bot.edit_message_text(
                f"💸 درخواست برداشت #{req.id}\n🚫 توسط کاربر لغو شد",
                chat_id=chat_id, message_id=msg_id,
            )
        except Exception:
            pass


@router.message(Command("cancel"), WithdrawalFlow.waiting_amount)
@router.message(Command("cancel"), WithdrawalFlow.waiting_card)
@router.message(Command("cancel"), WithdrawalFlow.waiting_holder)
@router.message(Command("cancel"), WithdrawalFlow.confirming)
async def wd_cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ درخواست برداشت لغو شد.")
