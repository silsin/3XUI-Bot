"""مدیریت کیف پول‌های کاربران در پنل ادمین."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import User, UserWallet, WalletTransaction
from app.filters import IsAdmin
from app.keyboards import admin as kb
from app.services.wallet_balance_service import WalletBalanceService
from app.states import AdminFlow
from app.utils.formatting import money

logger = logging.getLogger(__name__)
router = Router(name="admin_wallet")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())


class AdminWalletCB:
    """Callback data برای مدیریت کیف پول."""
    
    @staticmethod
    def menu() -> str:
        return "wallet_menu:home"
    
    @staticmethod
    def view_user(user_id: int) -> str:
        return f"wallet_view:user:{user_id}"
    
    @staticmethod
    def edit_balance(user_id: int) -> str:
        return f"wallet_edit:balance:{user_id}"
    
    @staticmethod
    def toggle_enabled(user_id: int) -> str:
        return f"wallet_toggle:enabled:{user_id}"
    
    @staticmethod
    def disable_all() -> str:
        return "wallet_action:disable_all"
    
    @staticmethod
    def enable_all() -> str:
        return "wallet_action:enable_all"
    
    @staticmethod
    def stats() -> str:
        return "wallet_action:stats"
    
    @staticmethod
    def search_user() -> str:
        return "wallet_action:search"


# ────────────────── منوی کیف پول ──────────────────


async def show_wallet_menu(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش منوی مدیریت کیف پول."""
    wallet_service = WalletBalanceService(session)
    stats = await wallet_service.get_wallet_stats()
    
    text = (
        f"<b>💳 مدیریت کیف پول‌ها</b>\n\n"
        f"📊 آمار:\n"
        f"  • کیف پول فعال: {stats['active_wallets']}\n"
        f"  • کیف پول غیرفعال: {stats['inactive_wallets']}\n"
        f"  • موجودی کل: {money(stats['total_balance'])}\n"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 جستجو کاربر", callback_data=AdminWalletCB.search_user())
    builder.button(text="📊 آمار کامل", callback_data=AdminWalletCB.stats())
    builder.button(text="❌ غیرفعال کردن همه", callback_data=AdminWalletCB.disable_all())
    builder.button(text="✅ فعال کردن همه", callback_data=AdminWalletCB.enable_all())
    builder.button(text="🏠 بازگشت", callback_data=kb.AdminCB(action="home").pack())
    builder.adjust(1)
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data == AdminWalletCB.menu())
async def wallet_menu(call: CallbackQuery, session: AsyncSession) -> None:
    """دکمه منوی کیف پول."""
    await show_wallet_menu(call, session)


@router.callback_query(F.data == AdminWalletCB.search_user())
async def wallet_search_user(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست شناسه کاربر برای جستجو."""
    await state.set_state(AdminFlow.wallet_search)
    await call.message.answer(
        "شناسه کاربر (Telegram ID) یا نام کاربری (@username) را وارد کنید:"
    )
    await call.answer()


@router.message(AdminFlow.wallet_search)
async def wallet_search_result(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """جستجوی کاربر و نمایش موجودی."""
    await state.clear()
    
    query_str = message.text.strip()
    
    # جستجو بر اساس ID یا username
    user = None
    try:
        user_id = int(query_str)
        user = await session.get(User, user_id)
    except ValueError:
        # شاید username است
        username = query_str.lstrip("@")
        stmt = select(User).where(User.username == username)
        user = await session.scalar(stmt)
    
    if not user:
        await message.answer("❌ کاربری یافت نشد.")
        return
    
    # نمایش اطلاعات کیف پول
    wallet_service = WalletBalanceService(session)
    wallet = await wallet_service.get_or_create_wallet(user.id)
    
    text = (
        f"<b>کاربر:</b> {user.first_name or 'N/A'}\n"
        f"<b>ID:</b> <code>{user.id}</code>\n"
        f"<b>Username:</b> @{user.username or 'N/A'}\n\n"
        f"<b>💳 کیف پول:</b>\n"
        f"  موجودی: {money(wallet.balance)}\n"
        f"  وضعیت: {'✅ فعال' if wallet.is_enabled else '❌ غیرفعال'}\n"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ تغییر موجودی",
        callback_data=AdminWalletCB.edit_balance(user.id),
    )
    builder.button(
        text=f"{'🔒 غیرفعال' if wallet.is_enabled else '🔓 فعال'} کردن",
        callback_data=AdminWalletCB.toggle_enabled(user.id),
    )
    builder.button(text="🏠 بازگشت", callback_data=AdminWalletCB.menu())
    builder.adjust(1)
    
    await message.answer(text, reply_markup=builder.as_markup())


# ────────────────── تغییر موجودی ──────────────────


@router.callback_query(F.data.startswith("wallet_edit:balance:"))
async def wallet_edit_balance(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """شروع ویرایش موجودی."""
    user_id = int(call.data.split(":")[2])
    wallet_service = WalletBalanceService(session)
    balance = await wallet_service.get_balance(user_id)
    
    await state.set_state(AdminFlow.wallet_set_balance)
    await state.update_data(target_user_id=user_id)
    
    await call.message.answer(
        f"موجودی فعلی: {money(balance)}\n\n"
        f"موجودی جدید را وارد کنید (به تومان):"
    )
    await call.answer()


@router.message(AdminFlow.wallet_set_balance)
async def wallet_set_balance(
    message: Message, session: AsyncSession, state: FSMContext, admin: User
) -> None:
    """تنظیم موجودی جدید."""
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    
    try:
        new_balance = int(message.text.strip())
        if new_balance < 0:
            raise ValueError("موجودی نمی‌تواند منفی باشد")
    except ValueError as e:
        await message.answer(f"❌ خطا: {e}")
        return
    
    wallet_service = WalletBalanceService(session)
    await wallet_service.set_balance(
        target_user_id,
        new_balance,
        admin_id=admin.id,
        reason=f"تنظیم موجودی توسط ادمین",
    )
    await session.commit()
    
    await state.clear()
    await message.answer(
        f"✅ موجودی کاربر {target_user_id} به {money(new_balance)} تنظیم شد."
    )


# ────────────────── فعال/غیرفعال کردن ──────────────────


@router.callback_query(F.data.startswith("wallet_toggle:enabled:"))
async def wallet_toggle_enabled(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """تبدیل وضعیت فعال/غیرفعال."""
    user_id = int(call.data.split(":")[2])
    
    wallet_service = WalletBalanceService(session)
    wallet = await wallet_service.get_or_create_wallet(user_id)
    
    # تبدیل وضعیت
    new_state = not wallet.is_enabled
    await wallet_service.set_enabled(user_id, new_state)
    await session.commit()
    
    status_text = "✅ فعال" if new_state else "❌ غیرفعال"
    await call.answer(f"وضعیت کیف پول: {status_text}")
    
    # نمایش دوباره اطلاعات
    user = await session.get(User, user_id)
    if not user:
        await call.message.edit_text("❌ کاربر یافت نشد.")
        return
    
    wallet = await wallet_service.get_or_create_wallet(user.id)
    
    text = (
        f"<b>کاربر:</b> {user.first_name or 'N/A'}\n"
        f"<b>ID:</b> <code>{user.id}</code>\n"
        f"<b>Username:</b> @{user.username or 'N/A'}\n\n"
        f"<b>💳 کیف پول:</b>\n"
        f"  موجودی: {money(wallet.balance)}\n"
        f"  وضعیت: {'✅ فعال' if wallet.is_enabled else '❌ غیرفعال'}\n"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ تغییر موجودی",
        callback_data=AdminWalletCB.edit_balance(user.id),
    )
    builder.button(
        text=f"{'🔒 غیرفعال' if wallet.is_enabled else '🔓 فعال'} کردن",
        callback_data=AdminWalletCB.toggle_enabled(user.id),
    )
    builder.button(text="🏠 بازگشت", callback_data=AdminWalletCB.menu())
    builder.adjust(1)
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


# ────────────────── عملیات دسته‌جمعی ──────────────────


@router.callback_query(F.data == AdminWalletCB.disable_all())
async def wallet_disable_all(
    call: CallbackQuery, session: AsyncSession, admin: User
) -> None:
    """غیرفعال کردن همه کیف پول‌ها."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأیید", callback_data="wallet_action:confirm_disable_all")
    builder.button(text="❌ لغو", callback_data=AdminWalletCB.menu())
    builder.adjust(1)
    
    await call.message.edit_text(
        "⚠️ <b>تأیید لازم است</b>\n\n"
        "آیا تمام کیف پول‌ها غیرفعال شود؟",
        reply_markup=builder.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "wallet_action:confirm_disable_all")
async def wallet_confirm_disable_all(
    call: CallbackQuery, session: AsyncSession, admin: User
) -> None:
    """تأیید غیرفعال کردن همه."""
    wallet_service = WalletBalanceService(session)
    count = await wallet_service.disable_all_wallets(admin.id, "غیرفعال شدن دسته‌جمعی")
    await session.commit()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 بازگشت", callback_data=AdminWalletCB.menu())
    builder.adjust(1)
    
    await call.message.edit_text(
        f"✅ {count} کیف پول غیرفعال شد.",
        reply_markup=builder.as_markup()
    )
    await call.answer()


@router.callback_query(F.data == AdminWalletCB.enable_all())
async def wallet_enable_all(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """فعال کردن همه کیف پول‌ها."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأیید", callback_data="wallet_action:confirm_enable_all")
    builder.button(text="❌ لغو", callback_data=AdminWalletCB.menu())
    builder.adjust(1)
    
    await call.message.edit_text(
        "⚠️ <b>تأیید لازم است</b>\n\n"
        "آیا تمام کیف پول‌ها فعال شود؟",
        reply_markup=builder.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "wallet_action:confirm_enable_all")
async def wallet_confirm_enable_all(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """تأیید فعال کردن همه."""
    wallet_service = WalletBalanceService(session)
    count = await wallet_service.enable_all_wallets()
    await session.commit()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 بازگشت", callback_data=AdminWalletCB.menu())
    builder.adjust(1)
    
    await call.message.edit_text(
        f"✅ {count} کیف پول فعال شد.",
        reply_markup=builder.as_markup()
    )
    await call.answer()


# ────────────────── آمار ──────────────────


@router.callback_query(F.data == AdminWalletCB.stats())
async def wallet_stats(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش آمار کامل کیف پول."""
    wallet_service = WalletBalanceService(session)
    stats = await wallet_service.get_wallet_stats()
    
    # تعداد کاربران با موجودی
    stmt = select(func.count(UserWallet.id)).where(UserWallet.balance > 0)
    wallets_with_balance = await session.scalar(stmt) or 0
    
    text = (
        f"<b>📊 آمار کیف پول‌ها</b>\n\n"
        f"کیف پول فعال: {stats['active_wallets']}\n"
        f"کیف پول غیرفعال: {stats['inactive_wallets']}\n"
        f"موجودی کل: {money(stats['total_balance'])}\n"
        f"کاربران با موجودی: {wallets_with_balance}\n"
    )
    
    # تراکنش‌های اخیر
    stmt = select(WalletTransaction).order_by(
        WalletTransaction.created_at.desc()
    ).limit(5)
    recent_transactions = await session.scalars(stmt)
    
    if recent_transactions:
        text += "\n<b>آخرین تراکنش‌ها:</b>\n"
        for tx in recent_transactions:
            icon = "➕" if tx.amount > 0 else "➖"
            text += f"{icon} {money(abs(tx.amount))}\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 بازگشت", callback_data=AdminWalletCB.menu())
    builder.adjust(1)
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()
