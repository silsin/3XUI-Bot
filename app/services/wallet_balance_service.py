"""سرویس مدیریت کیف پول کاربران."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    User,
    UserWallet,
    WalletTransaction,
    WalletTransactionType,
    Order,
    utcnow,
)


class WalletBalanceService:
    """سرویس مدیریت موجودی کیف پول کاربران."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_wallet(self, user_id: int) -> UserWallet:
        """گرفتن یا ایجاد کیف پول کاربر."""
        stmt = select(UserWallet).where(UserWallet.user_id == user_id)
        wallet = await self.session.scalar(stmt)

        if wallet is None:
            wallet = UserWallet(user_id=user_id, balance=0, is_enabled=True)
            self.session.add(wallet)
            await self.session.flush()

        return wallet

    async def get_balance(self, user_id: int) -> int:
        """گرفتن موجودی فعلی کیف پول."""
        wallet = await self.get_or_create_wallet(user_id)
        return wallet.balance

    async def is_enabled(self, user_id: int) -> bool:
        """بررسی فعال بودن کیف پول کاربر."""
        wallet = await self.get_or_create_wallet(user_id)
        return wallet.is_enabled

    async def deposit(
        self,
        user_id: int,
        amount: int,
        transaction_type: WalletTransactionType = WalletTransactionType.ADMIN_DEPOSIT,
        admin_id: Optional[int] = None,
        admin_note: Optional[str] = None,
        order_id: Optional[int] = None,
    ) -> WalletTransaction:
        """افزایش موجودی کیف پول (واریز).

        Args:
            user_id: شناسه کاربر
            amount: مبلغ (باید مثبت باشد)
            transaction_type: نوع تراکنش
            admin_id: ادمین انجام‌دهنده (در صورت نیاز)
            admin_note: توضیح ادمین
            order_id: شناسه سفارش (در صورت نیاز)

        Returns:
            WalletTransaction: تراکنش ایجاد‌شده
        """
        if amount <= 0:
            raise ValueError("مبلغ واریز باید مثبت باشد")

        wallet = await self.get_or_create_wallet(user_id)
        balance_before = wallet.balance
        wallet.balance += amount
        wallet.updated_at = utcnow()

        transaction = WalletTransaction(
            wallet_id=wallet.id,
            user_id=user_id,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            order_id=order_id,
            admin_id=admin_id,
            admin_note=admin_note,
        )

        self.session.add(transaction)
        await self.session.flush()

        return transaction

    async def withdraw(
        self,
        user_id: int,
        amount: int,
        transaction_type: WalletTransactionType = WalletTransactionType.ADMIN_WITHDRAW,
        admin_id: Optional[int] = None,
        admin_note: Optional[str] = None,
        order_id: Optional[int] = None,
    ) -> WalletTransaction:
        """کاهش موجودی کیف پول (برداشت/خرج).

        Args:
            user_id: شناسه کاربر
            amount: مبلغ (باید مثبت باشد، منفی می‌شود در ذخیره)
            transaction_type: نوع تراکنش
            admin_id: ادمین انجام‌دهنده (در صورت نیاز)
            admin_note: توضیح ادمین
            order_id: شناسه سفارش (در صورت نیاز)

        Returns:
            WalletTransaction: تراکنش ایجاد‌شده

        Raises:
            ValueError: اگر موجودی ناکافی باشد
        """
        if amount <= 0:
            raise ValueError("مبلغ برداشت باید مثبت باشد")

        wallet = await self.get_or_create_wallet(user_id)

        if wallet.balance < amount:
            raise ValueError(
                f"موجودی ناکافی. موجودی: {wallet.balance} تومان، درخواست: {amount} تومان"
            )

        balance_before = wallet.balance
        wallet.balance -= amount
        wallet.updated_at = utcnow()

        transaction = WalletTransaction(
            wallet_id=wallet.id,
            user_id=user_id,
            transaction_type=transaction_type,
            amount=-amount,  # منفی برای برداشت
            balance_before=balance_before,
            balance_after=wallet.balance,
            order_id=order_id,
            admin_id=admin_id,
            admin_note=admin_note,
        )

        self.session.add(transaction)
        await self.session.flush()

        return transaction

    async def purchase(
        self, user_id: int, amount: int, order_id: int
    ) -> WalletTransaction:
        """خرید از کیف پول (کاهش موجودی).

        Args:
            user_id: شناسه کاربر
            amount: مبلغ خرید
            order_id: شناسه سفارش

        Returns:
            WalletTransaction: تراکنش ایجاد‌شده

        Raises:
            ValueError: اگر موجودی ناکافی باشد
        """
        return await self.withdraw(
            user_id=user_id,
            amount=amount,
            transaction_type=WalletTransactionType.PURCHASE,
            order_id=order_id,
        )

    async def get_transactions(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WalletTransaction], int]:
        """دریافت تاریخچه تراکنش‌های کاربر.

        Args:
            user_id: شناسه کاربر
            limit: تعداد حداکثر نتایج
            offset: شماره شروع

        Returns:
            tuple: (لیست تراکنش‌ها، تعداد کل)
        """
        # تعداد کل تراکنش‌ها
        count_stmt = select(WalletTransaction).where(
            WalletTransaction.user_id == user_id
        )
        total_count = await self.session.scalar(
            select(lambda: len(count_stmt))
        ) or 0
        
        # دریافت تراکنش‌ها با offset و limit
        stmt = (
            select(WalletTransaction)
            .where(WalletTransaction.user_id == user_id)
            .order_by(desc(WalletTransaction.created_at))
            .limit(limit)
            .offset(offset)
        )

        transactions = await self.session.scalars(stmt)
        
        # تعداد دقیق کل
        count_result = await self.session.scalar(
            select(func.count(WalletTransaction.id)).where(
                WalletTransaction.user_id == user_id
            )
        )
        
        return list(transactions), count_result or 0

    async def set_enabled(self, user_id: int, enabled: bool) -> UserWallet:
        """فعال/غیرفعال کردن کیف پول کاربر.

        Args:
            user_id: شناسه کاربر
            enabled: فعال (True) یا غیرفعال (False)

        Returns:
            UserWallet: کیف پول به‌روزرسانی‌شده
        """
        wallet = await self.get_or_create_wallet(user_id)
        wallet.is_enabled = enabled
        wallet.updated_at = utcnow()
        await self.session.flush()
        return wallet

    async def set_balance(
        self,
        user_id: int,
        new_balance: int,
        admin_id: int,
        reason: str,
    ) -> WalletTransaction:
        """تنظیم مستقیم موجودی کیف پول (فقط ادمین).

        Args:
            user_id: شناسه کاربر
            new_balance: موجودی جدید
            admin_id: ادمین انجام‌دهنده
            reason: دلیل تنظیم

        Returns:
            WalletTransaction: تراکنش ایجاد‌شده
        """
        wallet = await self.get_or_create_wallet(user_id)
        balance_before = wallet.balance
        amount = new_balance - balance_before

        wallet.balance = new_balance
        wallet.updated_at = utcnow()

        transaction_type = (
            WalletTransactionType.ADMIN_DEPOSIT
            if amount > 0
            else WalletTransactionType.ADMIN_WITHDRAW
        )

        transaction = WalletTransaction(
            wallet_id=wallet.id,
            user_id=user_id,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=new_balance,
            admin_id=admin_id,
            admin_note=reason,
        )

        self.session.add(transaction)
        await self.session.flush()

        return transaction

    async def disable_all_wallets(self, admin_id: int, reason: str = "") -> int:
        """غیرفعال کردن تمام کیف پول‌ها.

        Args:
            admin_id: ادمین انجام‌دهنده
            reason: دلیل غیرفعال‌سازی

        Returns:
            int: تعداد کیف پول‌های غیرفعال‌شده
        """
        stmt = select(UserWallet).where(UserWallet.is_enabled == True)
        wallets = await self.session.scalars(stmt)
        wallets_list = list(wallets)

        for wallet in wallets_list:
            wallet.is_enabled = False
            wallet.updated_at = utcnow()

        await self.session.flush()
        return len(wallets_list)

    async def enable_all_wallets(self) -> int:
        """فعال کردن تمام کیف پول‌ها.

        Returns:
            int: تعداد کیف پول‌های فعال‌شده
        """
        stmt = select(UserWallet).where(UserWallet.is_enabled == False)
        wallets = await self.session.scalars(stmt)
        wallets_list = list(wallets)

        for wallet in wallets_list:
            wallet.is_enabled = True
            wallet.updated_at = utcnow()

        await self.session.flush()
        return len(wallets_list)

    async def get_wallet_stats(self) -> dict:
        """دریافت آمار کلی کیف پول‌ها.

        Returns:
            dict: شامل تعداد کیف پول‌ها، موجودی کل، و ...
        """
        # تعداد کیف پول‌های فعال
        active_stmt = select(UserWallet).where(UserWallet.is_enabled == True)
        active_wallets = await self.session.scalars(active_stmt)
        active_count = len(list(active_wallets))

        # تعداد کیف پول‌های غیرفعال
        inactive_stmt = select(UserWallet).where(UserWallet.is_enabled == False)
        inactive_wallets = await self.session.scalars(inactive_stmt)
        inactive_count = len(list(inactive_wallets))

        # موجودی کل
        total_balance_stmt = select(UserWallet)
        all_wallets = await self.session.scalars(total_balance_stmt)
        total_balance = sum(w.balance for w in all_wallets)

        return {
            "active_wallets": active_count,
            "inactive_wallets": inactive_count,
            "total_balance": total_balance,
        }
