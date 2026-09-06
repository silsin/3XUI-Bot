"""سرویس مدیریت تخفیف‌ها و پیشنهادهای ویژه."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Duration, Offer, OfferType, OfferUse, Package


class AppliedOffer(NamedTuple):
    """نتیجه اعمال یک تخفیف روی یک پکیج."""
    offer: Offer
    original_price: int
    final_price: int
    discount_amount: int        # مبلغ تخفیف (تومان)
    bonus_traffic_mb: int       # حجم اضافه (مگابایت)


def _is_valid(offer: Offer, now: datetime) -> bool:
    """بررسی اعتبار زمانی و وضعیت تخفیف."""
    if not offer.is_active:
        return False
    if offer.valid_from and now < offer.valid_from:
        return False
    if offer.valid_until and now > offer.valid_until:
        return False
    if offer.max_uses > 0 and offer.used_count >= offer.max_uses:
        return False
    return True


def calc_discount(offer: Offer, base_price: int) -> tuple[int, int, int]:
    """
    محاسبه تخفیف و حجم اضافه.
    برمی‌گرداند: (final_price, discount_amount, bonus_traffic_mb)
    """
    if offer.offer_type == OfferType.PERCENT:
        pct = max(0, min(100, offer.value))
        discount = int(base_price * pct / 100)
        return max(0, base_price - discount), discount, 0

    elif offer.offer_type == OfferType.FIXED:
        discount = min(offer.value, base_price)
        return max(0, base_price - discount), discount, 0

    elif offer.offer_type == OfferType.EXTRA_TRAFFIC:
        return base_price, 0, offer.value

    return base_price, 0, 0


async def get_active_offers(session: AsyncSession) -> list[Offer]:
    """همه تخفیف‌های فعال (برای نمایش در بنر)."""
    now = datetime.now(timezone.utc)
    stmt = select(Offer).where(
        Offer.is_active.is_(True),
        and_(
            (Offer.valid_from.is_(None)) | (Offer.valid_from <= now),
            (Offer.valid_until.is_(None)) | (Offer.valid_until >= now),
        ),
    ).order_by(Offer.id.desc())
    result = await session.execute(stmt)
    offers = list(result.scalars().all())
    return [o for o in offers if o.max_uses == 0 or o.used_count < o.max_uses]


async def find_auto_offers(
    session: AsyncSession,
    package: Package,
    user_id: int,
) -> list[Offer]:
    """
    تخفیف‌های بدون کد که به‌صورت خودکار روی این پکیج اعمال می‌شوند.
    فقط تخفیف‌هایی که کاربر هنوز از آن‌ها استفاده نکرده برمی‌گردند.
    """
    now = datetime.now(timezone.utc)
    stmt = select(Offer).where(
        Offer.is_active.is_(True),
        Offer.code.is_(None),  # بدون کد = خودکار
        and_(
            (Offer.valid_from.is_(None)) | (Offer.valid_from <= now),
            (Offer.valid_until.is_(None)) | (Offer.valid_until >= now),
        ),
        and_(
            (Offer.package_id.is_(None)) | (Offer.package_id == package.id),
            (Offer.duration_id.is_(None)) | (Offer.duration_id == package.duration_id),
        ),
    )
    result = await session.execute(stmt)
    candidates = list(result.scalars().all())

    valid = []
    for offer in candidates:
        if offer.max_uses > 0 and offer.used_count >= offer.max_uses:
            continue
        if offer.per_user > 0:
            uses = await _count_user_uses(session, offer.id, user_id)
            if uses >= offer.per_user:
                continue
        valid.append(offer)
    return valid


async def validate_code(
    session: AsyncSession,
    code: str,
    package: Package,
    user_id: int,
) -> tuple[Offer | None, str | None]:
    """
    اعتبارسنجی کد تخفیف.
    برمی‌گرداند: (offer, error_message)
    اگر offer برگردد خطایی نیست.
    """
    code = code.strip().upper()
    stmt = select(Offer).where(Offer.code == code)
    result = await session.execute(stmt)
    offer = result.scalar_one_or_none()

    if offer is None:
        return None, "❌ کد تخفیف نامعتبر است."

    now = datetime.now(timezone.utc)
    if not offer.is_active:
        return None, "❌ این کد تخفیف غیرفعال شده است."
    if offer.valid_from and now < offer.valid_from:
        return None, "❌ این کد هنوز فعال نشده است."
    if offer.valid_until and now > offer.valid_until:
        return None, "❌ مهلت استفاده از این کد به پایان رسیده است."
    if offer.max_uses > 0 and offer.used_count >= offer.max_uses:
        return None, "❌ ظرفیت این کد تخفیف تکمیل شده است."

    # بررسی محدودیت پکیج/مدت
    if offer.package_id and offer.package_id != package.id:
        return None, "❌ این کد برای این پکیج قابل استفاده نیست."
    if offer.duration_id and offer.duration_id != package.duration_id:
        return None, "❌ این کد برای این مدت اشتراک قابل استفاده نیست."

    # بررسی محدودیت تعداد استفاده توسط این کاربر
    if offer.per_user > 0:
        uses = await _count_user_uses(session, offer.id, user_id)
        if uses >= offer.per_user:
            return None, "❌ شما قبلاً از این کد تخفیف استفاده کرده‌اید."

    return offer, None


async def apply_offer(
    session: AsyncSession,
    offer: Offer,
    package: Package,
    user_id: int,
    order_id: int | None = None,
) -> AppliedOffer:
    """
    تخفیف را ثبت و اعمال می‌کند.
    این تابع را فقط هنگام ثبت نهایی سفارش فراخوانی کنید.
    """
    final_price, discount, bonus_mb = calc_discount(offer, package.price)

    # ثبت سابقه استفاده
    use = OfferUse(
        offer_id=offer.id,
        user_id=user_id,
        order_id=order_id,
    )
    session.add(use)
    offer.used_count += 1
    await session.commit()

    return AppliedOffer(
        offer=offer,
        original_price=package.price,
        final_price=final_price,
        discount_amount=discount,
        bonus_traffic_mb=bonus_mb,
    )


async def _count_user_uses(session: AsyncSession, offer_id: int, user_id: int) -> int:
    """تعداد دفعاتی که این کاربر از این تخفیف استفاده کرده."""
    stmt = select(func.count(OfferUse.id)).where(
        OfferUse.offer_id == offer_id,
        OfferUse.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


# ────────────────────── توابع CRUD برای ادمین ────────────────────────

async def get_all_offers(session: AsyncSession) -> list[Offer]:
    """همه تخفیف‌ها برای پنل ادمین."""
    result = await session.execute(select(Offer).order_by(Offer.id.desc()))
    return list(result.scalars().all())


async def get_offer(session: AsyncSession, offer_id: int) -> Offer | None:
    return await session.get(Offer, offer_id)


async def create_offer(session: AsyncSession, **kwargs) -> Offer:
    offer = Offer(**kwargs)
    session.add(offer)
    await session.commit()
    await session.refresh(offer)
    return offer


async def toggle_offer(session: AsyncSession, offer_id: int) -> Offer | None:
    offer = await session.get(Offer, offer_id)
    if offer:
        offer.is_active = not offer.is_active
        await session.commit()
    return offer


async def delete_offer(session: AsyncSession, offer_id: int) -> bool:
    offer = await session.get(Offer, offer_id)
    if offer:
        await session.delete(offer)
        await session.commit()
        return True
    return False


def offer_summary_text(offer: Offer) -> str:
    """خلاصه متنی یک تخفیف برای نمایش به کاربر."""
    if offer.offer_type == OfferType.PERCENT:
        return f"🏷 <b>{offer.title}</b>\n💸 {offer.value}٪ تخفیف"
    elif offer.offer_type == OfferType.FIXED:
        from app.utils.formatting import money
        return f"🏷 <b>{offer.title}</b>\n💸 {money(offer.value)} تومان تخفیف"
    elif offer.offer_type == OfferType.EXTRA_TRAFFIC:
        from app.utils.formatting import traffic
        return f"🎁 <b>{offer.title}</b>\n📦 {traffic(offer.value)} حجم اضافه"
    return f"🏷 <b>{offer.title}</b>"
