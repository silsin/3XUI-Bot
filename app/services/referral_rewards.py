"""پاداش کیف پول برای دعوت‌کننده (بر اساس کمپین‌های پاداش دعوت).

وقتی سفارش یک کاربر دعوت‌شده توسط ادمین تأیید می‌شود، اگر کمپین فعالی با
پکیج آن سفارش جور باشد، مبلغ کمپین به کیف پول دعوت‌کننده اضافه می‌شود.
برای هر دعوت‌شده در هر کمپین فقط یک‌بار پاداش داده می‌شود.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Order,
    ReferralCampaign,
    ReferralReward,
    User,
    WalletTransactionType,
    utcnow,
)
from app.services.wallet_balance_service import WalletBalanceService

logger = logging.getLogger(__name__)


def _aware(dt):
    from datetime import timezone
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def reward_inviter_for_order(
    session: AsyncSession, order: Order, buyer: User
) -> list[tuple[int, int]]:
    """پاداش را به کیف پول دعوت‌کننده اضافه می‌کند (commit با فراخواننده).

    فقط بهترین (بیشترین مبلغ) کمپین مشمول اعمال می‌شود.
    برمی‌گرداند: [(inviter_id, amount)] — خالی اگر پاداشی داده نشد.
    """
    if buyer.referrer_id is None or buyer.referrer_id == buyer.id:
        return []
    inviter = await session.get(User, buyer.referrer_id)
    if inviter is None:
        return []

    now = utcnow()
    campaigns = (
        await session.scalars(
            select(ReferralCampaign)
            .where(
                ReferralCampaign.is_active.is_(True),
                or_(
                    ReferralCampaign.package_id.is_(None),
                    ReferralCampaign.package_id == order.package_id,
                ),
            )
            .order_by(ReferralCampaign.reward_amount.desc())
        )
    ).all()

    for camp in campaigns:
        until = _aware(camp.valid_until)
        if until is not None and until <= now:
            continue
        if camp.max_rewards and camp.rewarded_count >= camp.max_rewards:
            continue
        already = await session.scalar(
            select(ReferralReward.id).where(
                ReferralReward.campaign_id == camp.id,
                ReferralReward.invitee_id == buyer.id,
            )
        )
        if already:
            continue

        try:
            async with session.begin_nested():
                # سقف تعداد پاداش را اتمیک رزرو می‌کند
                res = await session.execute(
                    update(ReferralCampaign)
                    .where(
                        ReferralCampaign.id == camp.id,
                        or_(
                            ReferralCampaign.max_rewards == 0,
                            ReferralCampaign.rewarded_count < ReferralCampaign.max_rewards,
                        ),
                    )
                    .values(rewarded_count=ReferralCampaign.rewarded_count + 1)
                )
                if res.rowcount != 1:
                    continue
                session.add(
                    ReferralReward(
                        campaign_id=camp.id,
                        inviter_id=inviter.id,
                        invitee_id=buyer.id,
                        order_id=order.id,
                        amount=camp.reward_amount,
                    )
                )
                await session.flush()
                await WalletBalanceService(session).deposit(
                    inviter.id,
                    camp.reward_amount,
                    transaction_type=WalletTransactionType.REFERRAL_BONUS,
                    order_id=order.id,
                    admin_note=f"پاداش دعوت — کمپین «{camp.title}» (کاربر {buyer.id})",
                )
        except IntegrityError:
            continue  # پاداش همین دعوت‌شده قبلاً در این کمپین داده شده
        logger.info(
            "referral reward %s toman -> inviter %s (invitee %s, order %s, campaign %s)",
            camp.reward_amount, inviter.id, buyer.id, order.id, camp.id,
        )
        return [(inviter.id, camp.reward_amount)]
    return []
