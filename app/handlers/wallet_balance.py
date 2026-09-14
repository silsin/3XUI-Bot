"""بخش مدیریت کیف پول کاربران."""

from __future__ import annotations

import json
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User, WalletTransactionType
from app.keyboards import inline, reply
from app.services import activity_service as activity
from app.services import settings_service as cfg
from app.services.wallet_balance_service import WalletBalanceService
from app.states import WalletTopupFlow
from app.texts import BTN_WALLET_BALANCE
from app.utils.formatting import money

logger = logging.getLogger(__name__)
router = Router(name="wallet_balance")

# متون
MSG_WALLET_DISABLED = "⚠️ کیف پول در حال‌حاضر غیرفعال است."
MSG_WALLET_EMPTY = "کیف پول شما خالی است."
MSG_WALLET_NOT_FOUND = "کیف پول یافت نشد."


class WalletBalanceCB:
    """Callback data برای بخش کیف پول."""
    
    @staticmethod
    def history(page: int = 0) -> str:
        return f"wallet:history:{page}"
    
    @staticmethod
    def back() -> str:
        return "wallet:back"


async def _format_transaction_type(tx_type: WalletTransactionType) -> str:
    """تبدیل نوع تراکنش به متن فارسی."""
    type_labels = {
        WalletTransactionType.PURCHASE: "🛒 خرید",
        WalletTransactionType.ADMIN_DEPOSIT: "➕ واریز مدیریت",
        WalletTransactionType.ADMIN_WITHDRAW: "➖ برداشت مدیریت",
        WalletTransactionType.REFUND: "↩️ بازگشت",
        WalletTransactionType.OFFER_BONUS: "🎁 بونوس جشنواره",
        WalletTransactionType.REFERRAL_BONUS: "👥 بونوس معرفی",
    }
    return type_labels.get(tx_type, str(tx_type))


@router.message(F.text == BTN_WALLET_BALANCE)
async def show_wallet_menu(message: Message, session: AsyncSession, user: User) -> None:
    """نمایش صفحه اصلی کیف پول."""
    wallet_service = WalletBalanceService(session)
    
    # بررسی فعال بودن
    is_enabled = await wallet_service.is_enabled(user.id)
    if not is_enabled:
        await message.answer(MSG_WALLET_DISABLED, reply_markup=reply.main_menu())
        return
    
    # دریافت موجودی
    balance = await wallet_service.get_balance(user.id)
    
    text = (
        f"<b>💳 کیف پول شما</b>\n\n"
        f"موجودی: <b>{money(balance)} تومان</b>\n\n"
        f"از این کیف پول می‌توانید:\n"
        f"✓ برای خرید اشتراک پرداخت کنید\n"
        f"✓ تاریخچه تراکنش‌ها را مشاهده کنید\n\n"
        f"<i>💡 برای شارژ کیف پول از طریق پشتیبانی درخواست کنید.</i>"
    )
    
    if balance == 0:
        text += f"\n\n{MSG_WALLET_EMPTY}"
    
    await message.answer(text, reply_markup=wallet_menu_kb(balance > 0))
    await activity.log_activity(session, user.id, "view_wallet")


def wallet_menu_kb(has_balance: bool = False) -> inline.InlineKeyboardMarkup:
    """دکمه‌های منوی کیف پول."""
    builder = InlineKeyboardBuilder()
    
    # دکمه شارژ
    builder.button(
        text="➕ درخواست شارژ",
        callback_data="wallet:request_topup",
    )
    
    builder.button(
        text="📊 تاریخچه تراکنش‌ها",
        callback_data=WalletBalanceCB.history(0),
    )
    
    builder.button(
        text="🏠 بازگشت",
        callback_data=WalletBalanceCB.back(),
    )
    
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data.startswith("wallet:history:"))
async def show_wallet_history(
    call: CallbackQuery, session: AsyncSession, user: User
) -> None:
    """نمایش تاریخچه تراکنش‌های کیف پول."""
    try:
        page = int(call.data.split(":")[2])
    except (ValueError, IndexError):
        page = 0
    
    wallet_service = WalletBalanceService(session)
    
    # بررسی فعال بودن
    is_enabled = await wallet_service.is_enabled(user.id)
    if not is_enabled:
        await call.answer(MSG_WALLET_DISABLED, show_alert=True)
        return
    
    # دریافت تراکنش‌ها
    limit = 10
    offset = page * limit
    transactions, total_count = await wallet_service.get_transactions(
        user.id, limit=limit, offset=offset
    )
    
    if not transactions:
        await call.answer(MSG_WALLET_EMPTY, show_alert=True)
        return
    
    # ساخت متن
    text = (
        f"<b>📊 تاریخچه تراکنش‌ها</b>\n\n"
        f"تعداد کل: {total_count} تراکنش\n"
        f"صفحه {page + 1} از {(total_count + limit - 1) // limit}\n\n"
    )
    
    for tx in transactions:
        tx_type_label = await _format_transaction_type(tx.transaction_type)
        
        # آیکن بر اساس جهت تراکنش
        icon = "➕" if tx.amount > 0 else "➖"
        
        # تاریخ
        created_at = tx.created_at.strftime("%Y-%m-%d %H:%M") if tx.created_at else "—"
        
        text += (
            f"{icon} {tx_type_label}\n"
            f"  مبلغ: {money(abs(tx.amount))}\n"
            f"  موجودی بعد: {money(tx.balance_after)}\n"
            f"  تاریخ: {created_at}\n\n"
        )
    
    # دکمه‌های navigation
    builder = InlineKeyboardBuilder()
    
    if page > 0:
        builder.button(
            text="⬅️ صفحه قبل",
            callback_data=f"wallet:history:{page - 1}",
        )
    
    if (page + 1) * limit < total_count:
        builder.button(
            text="صفحه بعد ➡️",
            callback_data=f"wallet:history:{page + 1}",
        )
    
    builder.button(
        text="🏠 بازگشت",
        callback_data=WalletBalanceCB.back(),
    )
    
    builder.adjust(1, 1, 1)
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()
    await activity.log_activity(
        session, user.id, "view_wallet_history",
        {"page": page}
    )


@router.callback_query(F.data == "wallet:back")
async def wallet_back(
    call: CallbackQuery, session: AsyncSession, user: User
) -> None:
    """بازگشت به منوی اصلی کیف پول."""
    wallet_service = WalletBalanceService(session)
    balance = await wallet_service.get_balance(user.id)
    is_enabled = await wallet_service.is_enabled(user.id)
    
    if not is_enabled:
        await call.message.edit_text(MSG_WALLET_DISABLED, reply_markup=reply.main_menu())
        await call.answer()
        return
    
    text = (
        f"<b>💳 کیف پول شما</b>\n\n"
        f"موجودی: <b>{money(balance)} تومان</b>\n\n"
        f"از این کیف پول می‌توانید:\n"
        f"✓ برای خرید اشتراک پرداخت کنید\n"
        f"✓ تاریخچه تراکنش‌ها را مشاهده کنید\n\n"
        f"<i>💡 برای شارژ کیف پول از طریق پشتیبانی درخواست کنید.</i>"
    )
    
    if balance == 0:
        text += f"\n\n{MSG_WALLET_EMPTY}"
    
    await call.message.edit_text(
        text, reply_markup=wallet_menu_kb(balance > 0)
    )
    await call.answer()


@router.callback_query(F.data == "wallet:request_topup")
async def wallet_request_topup(
    call: CallbackQuery, state: FSMContext
) -> None:
    """شروع جریان درخواست شارژ - انتخاب مبلغ."""
    
    text = (
        f"<b>💳 درخواست شارژ کیف پول</b>\n\n"
        f"لطفاً مبلغ مورد نظر را انتخاب کنید یا مقدار دلخواه خود را وارد کنید:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="50,000 تومان", callback_data="wallet:topup_amount:50000")
    builder.button(text="100,000 تومان", callback_data="wallet:topup_amount:100000")
    builder.button(text="200,000 تومان", callback_data="wallet:topup_amount:200000")
    builder.button(text="500,000 تومان", callback_data="wallet:topup_amount:500000")
    builder.button(text="1,000,000 تومان", callback_data="wallet:topup_amount:1000000")
    builder.button(text="📝 مبلغ دلخواه", callback_data="wallet:topup_custom")
    builder.button(text="❌ لغو", callback_data="wallet:back")
    builder.adjust(1)
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("wallet:topup_amount:"))
async def wallet_topup_amount_selected(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, user: User
) -> None:
    """انتخاب مبلغ از دکمه‌های از پیش تعریف‌شده."""
    
    try:
        amount = int(call.data.split(":")[2])
    except (ValueError, IndexError):
        await call.answer("❌ مبلغ نامعتبر است", show_alert=True)
        return
    
    # ذخیره مبلغ در state
    await state.set_state(WalletTopupFlow.waiting_receipt)
    await state.update_data(amount=amount)
    
    # نمایش اطلاعات پرداخت
    card_number = await cfg.get(session, "card_number")
    card_holder = await cfg.get(session, "card_holder")
    
    text = (
        f"<b>💳 درخواست شارژ</b>\n\n"
        f"مبلغ درخواست‌شده: <b>{money(amount)} تومان</b>\n\n"
        f"لطفاً مبلغ <b>{money(amount)}</b> تومان را به کارت زیر واریز کنید:\n\n"
        f"شماره کارت: <code>{card_number}</code>\n"
        f"نام صاحب حساب: <b>{card_holder}</b>\n\n"
        f"پس از واریز، لطفاً تصویر رسید را ارسال کنید."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ لغو", callback_data="wallet:back")
    builder.adjust(1)
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data == "wallet:topup_custom")
async def wallet_topup_custom(
    call: CallbackQuery, state: FSMContext
) -> None:
    """ورود مبلغ دلخواه."""
    
    await state.set_state(WalletTopupFlow.waiting_amount)
    await call.message.answer("لطفاً مبلغ مورد نظر (به تومان) را وارد کنید:")
    await call.answer()


@router.message(WalletTopupFlow.waiting_amount)
async def wallet_topup_custom_amount(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    """دریافت مبلغ دلخواه از کاربر."""
    
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError("مبلغ باید بیشتر از صفر باشد")
        if amount > 10_000_000:
            raise ValueError("مبلغ حداکثر 10 میلیون تومان است")
    except ValueError as e:
        await message.answer(f"❌ خطا: {e}")
        return
    
    # ذخیره مبلغ و تغییر state
    await state.set_state(WalletTopupFlow.waiting_receipt)
    await state.update_data(amount=amount)
    
    # نمایش اطلاعات پرداخت
    card_number = await cfg.get(session, "card_number")
    card_holder = await cfg.get(session, "card_holder")
    
    text = (
        f"<b>💳 درخواست شارژ</b>\n\n"
        f"مبلغ درخواست‌شده: <b>{money(amount)} تومان</b>\n\n"
        f"لطفاً مبلغ <b>{money(amount)}</b> تومان را به کارت زیر واریز کنید:\n\n"
        f"شماره کارت: <code>{card_number}</code>\n"
        f"نام صاحب حساب: <b>{card_holder}</b>\n\n"
        f"پس از واریز، لطفاً تصویر رسید را ارسال کنید."
    )
    
    await message.answer(text)


@router.message(WalletTopupFlow.waiting_receipt, F.photo | F.document)
async def wallet_topup_receive_receipt(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    """دریافت رسید درخواست شارژ از کاربر."""
    from app.db.models import WalletTopupRequest, WalletTopupRequestStatus
    
    data = await state.get_data()
    amount = data.get("amount", 0)
    
    if not amount:
        await state.clear()
        await message.answer("❌ خطا: مبلغ یافت نشد")
        return
    
    # ذخیره رسید درخواست
    if message.photo:
        receipt_file_id = message.photo[-1].file_id
        is_document = False
    else:
        receipt_file_id = message.document.file_id
        is_document = True
    
    topup_request = WalletTopupRequest(
        user_id=user.id,
        amount=amount,
        receipt_file_id=receipt_file_id,
        receipt_is_document=is_document,
        status=WalletTopupRequestStatus.AWAITING_APPROVAL,
    )
    session.add(topup_request)
    await session.flush()
    await session.commit()
    await session.refresh(topup_request)
    
    await state.clear()
    
    text = (
        f"✅ <b>درخواست شارژ ثبت شد</b>\n\n"
        f"مبلغ: {money(amount)} تومان\n"
        f"شماره درخواست: #{topup_request.id}\n\n"
        f"رسید شما بررسی شد و به‌زودی توسط پشتیبانی تایید می‌شود.\n"
        f"پس از تایید، مبلغ به کیف پول شما اضافه خواهد شد."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 بازگشت", callback_data="wallet:back")
    builder.adjust(1)
    
    await message.answer(text, reply_markup=builder.as_markup())
    
    # اطلاع به ادمین‌ها
    targets = get_settings().receipts_targets
    if targets:
        caption = (
            f"💳 <b>درخواست شارژ جدید</b>\n\n"
            f"👤 کاربر: {user.first_name or ''}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"💰 مبلغ: {money(amount)} تومان\n"
            f"📋 شماره درخواست: #{topup_request.id}\n"
        )
        
        markup = InlineKeyboardBuilder()
        markup.button(
            text="✅ تایید",
            callback_data=f"topup_approve:{topup_request.id}",
        )
        markup.button(
            text="❌ رد",
            callback_data=f"topup_reject:{topup_request.id}",
        )
        markup.adjust(2)
        
        bot = message.bot
        sent: list[list[int]] = []
        
        for target in targets:
            try:
                if is_document:
                    msg = await bot.send_document(
                        target, receipt_file_id, caption=caption, reply_markup=markup.as_markup()
                    )
                else:
                    msg = await bot.send_photo(
                        target, receipt_file_id, caption=caption, reply_markup=markup.as_markup()
                    )
                sent.append([msg.chat.id, msg.message_id])
            except Exception:
                logger.exception("failed to notify admin for topup request %s", topup_request.id)
        
        topup_request.notify_msgs = json.dumps(sent)
        await session.commit()
    
    await activity.log_activity(session, user.id, "wallet_topup_request", {"amount": amount, "request_id": topup_request.id})


@router.message(WalletTopupFlow.waiting_receipt)
async def wallet_topup_receipt_invalid(message: Message) -> None:
    """پیام نامعتبر در مرحله ارسال رسید."""
    await message.answer("❌ لطفاً تصویر یا فایل رسید را ارسال کنید.")
