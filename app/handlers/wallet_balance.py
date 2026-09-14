"""بخش مدیریت کیف پول کاربران."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, WalletTransactionType
from app.keyboards import inline, reply
from app.services import activity_service as activity
from app.services.wallet_balance_service import WalletBalanceService
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
        f"✓ تاریخچه تراکنش‌ها را مشاهده کنید\n"
    )
    
    if balance == 0:
        text += f"\n{MSG_WALLET_EMPTY}"
    
    await message.answer(text, reply_markup=wallet_menu_kb(balance > 0))
    await activity.log_activity(session, user.id, "view_wallet")


def wallet_menu_kb(has_balance: bool = False) -> inline.InlineKeyboardMarkup:
    """دکمه‌های منوی کیف پول."""
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="📊 تاریخچه تراکنش‌ها",
        callback_data=WalletBalanceCB.history(0),
        style="primary",
    )
    
    builder.button(
        text="🏠 بازگشت",
        callback_data=WalletBalanceCB.back(),
        style="secondary",
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
            style="primary",
        )
    
    if (page + 1) * limit < total_count:
        builder.button(
            text="صفحه بعد ➡️",
            callback_data=f"wallet:history:{page + 1}",
            style="primary",
        )
    
    builder.button(
        text="🏠 بازگشت",
        callback_data=WalletBalanceCB.back(),
        style="secondary",
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
        await call.message.edit_text(MSG_WALLET_DISABLED)
        await call.answer()
        return
    
    text = (
        f"<b>💳 کیف پول شما</b>\n\n"
        f"موجودی: <b>{money(balance)} تومان</b>\n\n"
        f"از این کیف پول می‌توانید:\n"
        f"✓ برای خرید اشتراک پرداخت کنید\n"
        f"✓ تاریخچه تراکنش‌ها را مشاهده کنید\n"
    )
    
    if balance == 0:
        text += f"\n{MSG_WALLET_EMPTY}"
    
    await call.message.edit_text(
        text, reply_markup=wallet_menu_kb(balance > 0)
    )
    await call.answer()
