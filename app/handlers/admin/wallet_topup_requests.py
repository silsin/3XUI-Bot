"""مدیریت درخواست‌های شارژ کیف پول در پنل ادمین."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    User,
    WalletTopupRequest,
    WalletTopupRequestStatus,
    WalletTransactionType,
)
from app.filters import IsAdmin
from app.services.wallet_balance_service import WalletBalanceService
from app.utils.formatting import money

logger = logging.getLogger(__name__)
router = Router(name="admin_wallet_topup")
router.callback_query.filter(IsAdmin())


class AdminTopupCB:
    """Callback data برای مدیریت درخواست‌های شارژ."""

    @staticmethod
    def approve(request_id: int) -> str:
        return f"topup_approve:{request_id}"

    @staticmethod
    def reject(request_id: int) -> str:
        return f"topup_reject:{request_id}"


@router.callback_query(F.data.startswith("topup_approve:"))
async def topup_approve(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """تایید درخواست شارژ."""
    try:
        request_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer("❌ خطا: شناسه نامعتبر", show_alert=True)
        return

    topup_request = await session.get(WalletTopupRequest, request_id)
    if not topup_request:
        await call.answer("❌ درخواست یافت نشد", show_alert=True)
        return

    if topup_request.status != WalletTopupRequestStatus.AWAITING_APPROVAL:
        await call.answer("❌ این درخواست قبلاً بررسی شده است", show_alert=True)
        return

    # تایید درخواست و اضافه‌کردن به کیف پول
    from datetime import datetime, timezone

    admin_id = call.from_user.id
    topup_request.status = WalletTopupRequestStatus.APPROVED
    topup_request.admin_id = admin_id
    topup_request.decided_at = datetime.now(timezone.utc)

    wallet_service = WalletBalanceService(session)
    await wallet_service.deposit(
        topup_request.user_id,
        topup_request.amount,
        transaction_type=WalletTransactionType.ADMIN_DEPOSIT,
        admin_id=admin_id,
        admin_note=f"تایید درخواست شارژ #{topup_request.id}",
    )

    await session.commit()

    text = (
        f"✅ <b>درخواست تایید شد</b>\n\n"
        f"کاربر: {topup_request.user_id}\n"
        f"مبلغ: {money(topup_request.amount)} تومان\n"
        f"شماره درخواست: #{topup_request.id}\n\n"
        f"مبلغ به کیف پول کاربر اضافه شد."
    )

    await call.message.edit_text(text)
    await call.answer("✅ درخواست تایید شد")

    # اطلاع به کاربر
    try:
        await call.bot.send_message(
            topup_request.user_id,
            f"✅ <b>درخواست شارژ تایید شد</b>\n\n"
            f"مبلغ {money(topup_request.amount)} تومان به کیف پول شما اضافه شد.\n"
            f"شماره درخواست: #{topup_request.id}",
        )
    except Exception:
        logger.exception("Failed to notify user %s about topup approval", topup_request.user_id)


@router.callback_query(F.data.startswith("topup_reject:"))
async def topup_reject(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """رد درخواست شارژ."""
    try:
        request_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer("❌ خطا: شناسه نامعتبر", show_alert=True)
        return

    topup_request = await session.get(WalletTopupRequest, request_id)
    if not topup_request:
        await call.answer("❌ درخواست یافت نشد", show_alert=True)
        return

    if topup_request.status != WalletTopupRequestStatus.AWAITING_APPROVAL:
        await call.answer("❌ این درخواست قبلاً بررسی شده است", show_alert=True)
        return

    # رد درخواست
    from datetime import datetime, timezone

    admin_id = call.from_user.id
    topup_request.status = WalletTopupRequestStatus.REJECTED
    topup_request.admin_id = admin_id
    topup_request.decided_at = datetime.now(timezone.utc)
    topup_request.admin_note = "درخواست توسط ادمین رد شد"

    await session.commit()

    text = (
        f"❌ <b>درخواست رد شد</b>\n\n"
        f"کاربر: {topup_request.user_id}\n"
        f"مبلغ: {money(topup_request.amount)} تومان\n"
        f"شماره درخواست: #{topup_request.id}\n\n"
        f"درخواست توسط ادمین رد شده است."
    )

    await call.message.edit_text(text)
    await call.answer("✅ درخواست رد شد")

    # اطلاع به کاربر
    try:
        await call.bot.send_message(
            topup_request.user_id,
            f"❌ <b>درخواست شارژ رد شد</b>\n\n"
            f"درخواست شارژ {money(topup_request.amount)} تومان رد شده است.\n"
            f"شماره درخواست: #{topup_request.id}\n\n"
            f"برای اطلاع بیشتر به پشتیبانی مراجعه کنید.",
        )
    except Exception:
        logger.exception("Failed to notify user %s about topup rejection", topup_request.user_id)
