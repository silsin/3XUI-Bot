"""امتیاز و زیرمجموعه‌گیری (رفرال)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PointsEntry, User
from app.services import settings_service as cfg
from app.texts import S_POINTS_PER_DAY, S_REFERRAL_POINTS


async def add_points(
    session: AsyncSession,
    user: User,
    delta: int,
    reason: str,
    ref_user_id: int | None = None,
) -> None:
    user.points = max(0, user.points + delta)
    session.add(
        PointsEntry(
            user_id=user.id, delta=delta, reason=reason, ref_user_id=ref_user_id
        )
    )
    await session.commit()


async def count_referrals(session: AsyncSession, user_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count(User.id)).where(User.referrer_id == user_id)
            )
        ).scalar()
        or 0
    )


async def count_successful_referrals(session: AsyncSession, user_id: int) -> int:
    """دعوت‌هایی که به خرید رسیده‌اند (پاداش گرفته‌اند)."""
    return int(
        (
            await session.execute(
                select(func.count(User.id)).where(
                    User.referrer_id == user_id, User.referral_rewarded.is_(True)
                )
            )
        ).scalar()
        or 0
    )


async def reward_referrer_on_first_purchase(
    session: AsyncSession, buyer: User
) -> tuple[User, int] | None:
    """
    پس از اولین خرید تأییدشده، به معرف امتیاز می‌دهد.
    فقط یک‌بار برای هر کاربر معرفی‌شده اجرا می‌شود.
    """
    if buyer.referrer_id is None or buyer.referral_rewarded:
        return None
    referrer = await session.get(User, buyer.referrer_id)
    if referrer is None or referrer.id == buyer.id:
        return None

    points = await cfg.get_int(session, S_REFERRAL_POINTS, 10)
    buyer.referral_rewarded = True
    await add_points(session, referrer, points, "referral", ref_user_id=buyer.id)
    return referrer, points


async def points_to_days(session: AsyncSession, points: int) -> int:
    per_day = await cfg.get_int(session, S_POINTS_PER_DAY, 10)
    if per_day <= 0:
        return 0
    return points // per_day


async def spend_points_for_days(
    session: AsyncSession, user: User, days: int
) -> bool:
    """امتیاز را برای دریافت روز اشتراک کسر می‌کند."""
    per_day = await cfg.get_int(session, S_POINTS_PER_DAY, 10)
    cost = per_day * days
    if per_day <= 0 or days <= 0 or user.points < cost:
        return False
    await add_points(session, user, -cost, f"redeem:{days}d")
    return True
