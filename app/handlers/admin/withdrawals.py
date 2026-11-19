"""مدیریت درخواست‌های برداشت کیف پول — سمت ادمین."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, WithdrawalRequest, WithdrawalStatus
from app.filters import IsAdmin
from app.services import withdrawal_service as wd
from app.services.wallet_balance_service import WalletBalanceService
from app.states import WithdrawalAdminFlow
from app.utils.formatting import money

logger = logging.getLogger(__name__)
router = Router(name="admin_withdrawals")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


def admin_request_text(req: WithdrawalRequest, user: User, status: str = "") -> str:
    text = (
        f"💸 <b>درخواست برداشت کیف پول</b> #{req.id}\n\n"
        f"👤 کاربر: {user.first_name or ''} (<code>{user.id}</code>)\n"
        f"💰 مبلغ: <b>{money(req.amount)} تومان</b>\n"
        f"💳 کارت: <code>{req.card_number}</code>\n"
        f"🏷 صاحب کارت: {req.card_holder}\n"
        f"(مبلغ از کیف پول کاربر کسر شده است)"
    )
    if status:
        text += f"\n\n{status}"
    return text


def admin_request_markup(request_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ تایید", callback_data=f"wd_approve:{request_id}")
    b.button(text="❌ رد", callback_data=f"wd_reject:{request_id}")
    b.adjust(2)
    return b.as_markup()


def _receipt_markup(request_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="📸 ارسال رسید واریز", callback_data=f"wd_receipt:{request_id}")
    return b.as_markup()


def _rid(call: CallbackQuery) -> int | None:
    try:
        return int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return None


async def _update_all(bot, req: WithdrawalRequest, text: str, markup=None) -> None:
    """پیام همه ادمین‌ها را به‌روز می‌کند (تا دو ادمین همزمان اقدام نکنند)."""
    for chat_id, msg_id in json.loads(req.notify_msgs or "[]"):
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=msg_id, reply_markup=markup
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("wd_approve:"))
async def wd_approve(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    rid = _rid(call)
    if rid is None:
        await call.answer("❌ نامعتبر", show_alert=True)
        return
    try:
        req = await wd.approve(session, rid, call.from_user.id)
        await session.commit()
    except wd.WithdrawalError as exc:
        await session.rollback()
        await call.answer(f"❌ {exc}", show_alert=True)
        return
    user = await session.get(User, req.user_id)
    await _update_all(
        call.bot, req,
        admin_request_text(req, user, "✅ تایید شد — پس از واریز، رسید را ارسال کنید."),
        _receipt_markup(req.id),
    )
    await call.answer("✅ تایید شد")
    # بلافاصله منتظر رسید همین ادمین
    await state.set_state(WithdrawalAdminFlow.waiting_receipt)
    await state.update_data(withdrawal_id=req.id)
    await call.message.answer(
        f"💳 مبلغ <b>{money(req.amount)}</b> تومان را به کارت "
        f"<code>{req.card_number}</code> ({req.card_holder}) واریز کنید، "
        f"سپس <b>تصویر رسید</b> را اینجا بفرستید."
    )
    try:
        await call.bot.send_message(
            req.user_id,
            f"✅ درخواست برداشت #{req.id} تایید شد.\n"
            f"پس از واریز، رسید برای شما ارسال می‌شود.",
        )
    except Exception:
        logger.exception("notify user %s failed", req.user_id)


@router.callback_query(F.data.startswith("wd_reject:"))
async def wd_reject(call: CallbackQuery, session: AsyncSession) -> None:
    rid = _rid(call)
    if rid is None:
        await call.answer("❌ نامعتبر", show_alert=True)
        return
    try:
        req = await wd.reject(session, rid, call.from_user.id)
        await session.commit()
    except wd.WithdrawalError as exc:
        await session.rollback()
        await call.answer(f"❌ {exc}", show_alert=True)
        return
    user = await session.get(User, req.user_id)
    await _update_all(
        call.bot, req, admin_request_text(req, user, "❌ رد شد — مبلغ به کیف پول برگشت.")
    )
    await call.answer("❌ رد شد")
    try:
        await call.bot.send_message(
            req.user_id,
            f"❌ درخواست برداشت #{req.id} رد شد.\n"
            f"مبلغ {money(req.amount)} تومان به کیف پول شما برگشت.",
        )
    except Exception:
        logger.exception("notify user %s failed", req.user_id)


@router.callback_query(F.data.startswith("wd_receipt:"))
async def wd_receipt_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    rid = _rid(call)
    req = await session.get(WithdrawalRequest, rid) if rid else None
    if req is None or req.status != WithdrawalStatus.APPROVED:
        await call.answer("❌ این درخواست در انتظار رسید نیست.", show_alert=True)
        return
    await state.set_state(WithdrawalAdminFlow.waiting_receipt)
    await state.update_data(withdrawal_id=req.id)
    await call.message.answer(f"📸 تصویر رسید واریز درخواست #{req.id} را بفرستید.")
    await call.answer()


@router.message(Command("cancel"), WithdrawalAdminFlow.waiting_receipt)
async def wd_receipt_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "انصراف داده شد. برای ارسال رسید بعداً از دکمه «ارسال رسید واریز» استفاده کنید."
    )


@router.message(WithdrawalAdminFlow.waiting_receipt, F.photo | F.document)
async def wd_receipt_receive(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    rid = data.get("withdrawal_id")
    if message.photo:
        file_id, is_doc = message.photo[-1].file_id, False
    else:
        file_id, is_doc = message.document.file_id, True
    try:
        req = await wd.complete(session, rid, message.from_user.id, file_id, is_doc)
        await session.commit()
    except wd.WithdrawalError as exc:
        await session.rollback()
        await state.clear()
        await message.answer(f"❌ {exc}")
        return
    await state.clear()

    user = await session.get(User, req.user_id)
    balance = await WalletBalanceService(session).get_balance(req.user_id)
    caption = (
        f"✅ <b>برداشت شما انجام شد</b>\n\n"
        f"مبلغ {money(req.amount)} تومان به کارت <code>{req.card_number}</code> "
        f"واریز شد.\nشماره درخواست: #{req.id}\n"
        f"موجودی فعلی کیف پول: <b>{money(balance)} تومان</b>"
    )
    delivered = True
    try:
        if is_doc:
            await message.bot.send_document(req.user_id, file_id, caption=caption)
        else:
            await message.bot.send_photo(req.user_id, file_id, caption=caption)
    except Exception:
        delivered = False
        logger.exception("send receipt to user %s failed", req.user_id)

    await _update_all(
        message.bot, req, admin_request_text(req, user, "🏁 واریز شد و رسید ارسال گردید.")
    )
    await message.answer(
        f"✅ درخواست #{req.id} تکمیل شد."
        + ("" if delivered else "\n⚠️ ارسال رسید به کاربر ناموفق بود (ربات را بلاک کرده؟).")
    )


@router.message(WithdrawalAdminFlow.waiting_receipt)
async def wd_receipt_invalid(message: Message) -> None:
    await message.answer("❌ لطفاً تصویر یا فایل رسید را ارسال کنید (/cancel برای انصراف).")
