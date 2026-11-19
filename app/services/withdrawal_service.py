"""منطق درخواست برداشت از کیف پول.

مبلغ همان لحظه ثبت درخواست از کیف پول کسر (نگه‌داری) می‌شود تا کاربر نتواند
همزمان آن را خرج کند. در صورت رد/لغو، مبلغ با تراکنش REFUND برمی‌گردد.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    WalletTransactionType,
    WithdrawalRequest,
    WithdrawalStatus,
    utcnow,
)
from app.services.wallet_balance_service import WalletBalanceService

MIN_WITHDRAWAL = 10_000          # تومان
MAX_WITHDRAWAL = 50_000_000      # تومان

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class WithdrawalError(Exception):
    """خطای کسب‌وکار؛ پیام فارسی برای نمایش به کاربر/ادمین."""


def validate_amount(amount: int, balance: int) -> str | None:
    if amount < MIN_WITHDRAWAL:
        return f"حداقل مبلغ برداشت {MIN_WITHDRAWAL:,} تومان است."
    if amount > MAX_WITHDRAWAL:
        return f"حداکثر مبلغ برداشت {MAX_WITHDRAWAL:,} تومان است."
    if amount > balance:
        return "مبلغ از موجودی کیف پول بیشتر است."
    return None


def parse_card(text: str) -> str | None:
    digits = "".join(ch for ch in text.translate(_FA_DIGITS) if ch.isdigit())
    return digits if len(digits) == 16 else None


async def has_open_request(session: AsyncSession, user_id: int) -> bool:
    row = await session.scalar(
        select(WithdrawalRequest.id).where(
            WithdrawalRequest.user_id == user_id,
            WithdrawalRequest.status.in_(
                [WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED]
            ),
        ).limit(1)
    )
    return row is not None


async def create_request(
    session: AsyncSession, user_id: int, amount: int,
    card_number: str, card_holder: str,
) -> WithdrawalRequest:
    """ثبت درخواست و کسر فوری مبلغ از کیف پول. commit با فراخواننده است."""
    wallets = WalletBalanceService(session)
    if not await wallets.is_enabled(user_id):
        raise WithdrawalError("کیف پول غیرفعال است.")
    if await has_open_request(session, user_id):
        raise WithdrawalError("شما یک درخواست برداشت در حال بررسی دارید.")
    err = validate_amount(amount, await wallets.get_balance(user_id))
    if err:
        raise WithdrawalError(err)

    req = WithdrawalRequest(
        user_id=user_id, amount=amount,
        card_number=card_number, card_holder=card_holder,
        status=WithdrawalStatus.PENDING,
    )
    session.add(req)
    await session.flush()
    try:
        await wallets.withdraw(
            user_id, amount,
            transaction_type=WalletTransactionType.WITHDRAWAL,
            admin_note=f"درخواست برداشت #{req.id}",
        )
    except ValueError as exc:
        raise WithdrawalError(str(exc)) from exc
    return req


async def _claim(
    session: AsyncSession, request_id: int,
    from_status: WithdrawalStatus, to_status: WithdrawalStatus, **values,
) -> WithdrawalRequest:
    """انتقال اتمیک وضعیت؛ جلوی دوبار تایید/رد همزمان را می‌گیرد."""
    res = await session.execute(
        update(WithdrawalRequest)
        .where(WithdrawalRequest.id == request_id,
               WithdrawalRequest.status == from_status)
        .values(status=to_status, **values)
    )
    if res.rowcount != 1:
        raise WithdrawalError("این درخواست قبلاً بررسی شده است.")
    return await session.get(WithdrawalRequest, request_id, populate_existing=True)


async def _refund(session: AsyncSession, req: WithdrawalRequest, note: str) -> None:
    await WalletBalanceService(session).deposit(
        req.user_id, req.amount,
        transaction_type=WalletTransactionType.REFUND,
        admin_id=req.admin_id, admin_note=note,
    )


async def approve(session: AsyncSession, request_id: int, admin_id: int) -> WithdrawalRequest:
    return await _claim(
        session, request_id, WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED,
        admin_id=admin_id, decided_at=utcnow(),
    )


async def reject(session: AsyncSession, request_id: int, admin_id: int) -> WithdrawalRequest:
    req = await _claim(
        session, request_id, WithdrawalStatus.PENDING, WithdrawalStatus.REJECTED,
        admin_id=admin_id, decided_at=utcnow(), admin_note="رد توسط ادمین",
    )
    await _refund(session, req, f"بازگشت مبلغ برداشت ردشده #{req.id}")
    return req


async def cancel_by_user(session: AsyncSession, request_id: int, user_id: int) -> WithdrawalRequest:
    req = await session.get(WithdrawalRequest, request_id)
    if req is None or req.user_id != user_id:
        raise WithdrawalError("درخواست یافت نشد.")
    req = await _claim(
        session, request_id, WithdrawalStatus.PENDING, WithdrawalStatus.CANCELLED,
        decided_at=utcnow(), admin_note="لغو توسط کاربر",
    )
    await _refund(session, req, f"بازگشت مبلغ برداشت لغوشده #{req.id}")
    return req


async def complete(
    session: AsyncSession, request_id: int, admin_id: int,
    file_id: str, is_document: bool,
) -> WithdrawalRequest:
    return await _claim(
        session, request_id, WithdrawalStatus.APPROVED, WithdrawalStatus.COMPLETED,
        admin_id=admin_id, receipt_file_id=file_id,
        receipt_is_document=is_document, completed_at=utcnow(),
    )
