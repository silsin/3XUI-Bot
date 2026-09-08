"""منطق تقسیم سرویس (split) و انتقال به کاربر دیگر — ساده‌شده.

این ماژول لایه میانی بین هندلر و provisioning است:
- اعتبارسنجی سرویس قابل تقسیم
- فراخوانی provisioning.split_service با اندازه‌های پیش‌تعریف‌شده
- جستجوی کاربر بر اساس username (@username lookup)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Service, ServiceStatus, User
from app.services.provisioning import split_service
from app.services.vpn.base import VpnError

logger = logging.getLogger(__name__)

# حداقل حجمی که می‌توان جدا کرد
MIN_SPLIT_MB = 100   # ۱۰۰ مگابایت

# اندازه‌های استاندارد پیش‌فرض
STANDARD_SIZES = {
    "1gb": 1024,
    "2gb": 2048,
    "5gb": 5120,
    "10gb": 10240,
    "20gb": 20480,
    "50gb": 51200,
}


@dataclass(slots=True)
class SplitError(Exception):
    """خطای اعتبارسنجی یا کسب‌وکار در عملیات تقسیم."""
    message: str

    def __str__(self) -> str:
        return self.message


def available_mb(service: Service) -> int:
    """حجم موجود برای تقسیم (با احتساب مصرف‌شده)."""
    if service.traffic_mb == 0:
        return 0   # نامحدود — قابل تقسیم نیست (مشخص نیست چقدر باقی مانده)
    used_mb = service.used_bytes // (1024 * 1024)
    return max(0, service.traffic_mb - used_mb)


def _is_active_splittable(service: Service) -> bool:
    """آیا این سرویس می‌تواند تقسیم شود؟"""
    if service.status is not ServiceStatus.ACTIVE:
        return False
    if service.traffic_mb == 0:
        return False   # نامحدود — تقسیم ندارد
    if service.is_trial:
        return False   # سرویس تست قابل تقسیم نیست
    # حداقل MIN_SPLIT_MB حجم آزاد داشته باشد
    if available_mb(service) < MIN_SPLIT_MB:
        return False
    # منقضی نشده باشد
    if service.expires_at is not None:
        exp = service.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            return False
    return True


# ─────────────────────── توابع اصلی ────────────────────────────────

# ─────────────────────── توابع اصلی ────────────────────────────

async def get_splittable_services(
    session: AsyncSession, user_id: int
) -> list[Service]:
    """لیست سرویس‌های فعال کاربر که قابل تقسیم هستند.

    شرایط: فعال، دارای quota مشخص (نه نامحدود)، حداقل MIN_SPLIT_MB آزاد.
    """
    rows = list(
        (
            await session.execute(
                select(Service)
                .where(
                    Service.user_id == user_id,
                    Service.status == ServiceStatus.ACTIVE,
                )
                .order_by(Service.created_at.desc())
            )
        ).scalars().all()
    )
    return [s for s in rows if _is_active_splittable(s)]


def _is_active_splittable(service: Service) -> bool:
    """آیا این سرویس می‌تواند تقسیم شود؟"""
    if service.status is not ServiceStatus.ACTIVE:
        return False
    if service.traffic_mb == 0:
        return False   # نامحدود
    if service.is_trial:
        return False
    if available_mb(service) < MIN_SPLIT_MB:
        return False
    # منقضی نشده باشد
    if service.expires_at is not None:
        exp = service.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            return False
    return True


def available_mb(service: Service) -> int:
    """حجم موجود برای تقسیم (بدون احتساب مصرف)."""
    if service.traffic_mb == 0:
        return 0   # نامحدود
    used_mb = service.used_bytes // (1024 * 1024)
    return max(0, service.traffic_mb - used_mb)


async def validate_split(
    session: AsyncSession,
    parent: Service,
    allocated_mb: int,
    owner_id: int,
) -> str | None:
    """اعتبارسنجی نهایی قبل از split.

    برمی‌گرداند: پیام خطا (فارسی) یا None اگر معتبر باشد.
    """
    if parent.user_id != owner_id:
        return "این سرویس به شما تعلق ندارد."

    if not _is_active_splittable(parent):
        if parent.status is not ServiceStatus.ACTIVE:
            return "سرویس فعال نیست."
        if parent.traffic_mb == 0:
            return "سرویس‌های نامحدود قابل تقسیم نیستند."
        if parent.is_trial:
            return "سرویس تست قابل تقسیم نیست."
        return "سرویس حجم کافی برای تقسیم ندارد."

    avail = available_mb(parent)
    if allocated_mb > avail:
        return (
            f"حجم درخواستی ({allocated_mb:,} MB) از موجودی آزاد "
            f"({avail:,} MB) بیشتر است."
        )

    if allocated_mb < MIN_SPLIT_MB:
        return f"حداقل حجم قابل تقسیم {MIN_SPLIT_MB} مگابایت است."

    # بعد از تقسیم، حداقل MIN_SPLIT_MB برای والد باقی بماند
    remainder = avail - allocated_mb
    if remainder > 0 and remainder < MIN_SPLIT_MB:
        return (
            f"پس از تقسیم، {remainder:,} MB برای سرویس اصلی باقی می‌ماند "
            f"که کمتر از حداقل مجاز ({MIN_SPLIT_MB} MB) است. "
            f"حداکثر {avail - MIN_SPLIT_MB:,} MB می‌توانید جدا کنید."
        )

    return None


async def do_split(
    session: AsyncSession,
    *,
    parent: Service,
    allocated_mb: int,
    recipient: User,
    title: str = "",
    owner_id: int,
) -> Service:
    """تقسیم سرویس والد و ساخت سرویس فرزند.

    پرتاب می‌کند: SplitError در صورت بروز خطا.
    """
    err = await validate_split(session, parent, allocated_mb, owner_id)
    if err:
        raise SplitError(err)

    try:
        child = await split_service(
            session,
            parent=parent,
            allocated_mb=allocated_mb,
            recipient=recipient,
            title=title or f"کانفیگ {allocated_mb} MB",
        )
    except VpnError as exc:
        raise SplitError(f"خطا در ساخت سرویس: {exc}") from exc

    return child


async def get_user_by_username(
    session: AsyncSession, username: str
) -> User | None:
    """جستجوی کاربر بر اساس username (بدون @ یا با @).

    مثال: «john» یا «@john» → User با username='john'
    """
    raw = username.strip().lstrip("@").lower()
    if not raw or len(raw) < 3:
        return None

    return (
        await session.execute(
            select(User).where(
                User.username == raw
            )
        )
    ).scalar_one_or_none()


async def get_user_by_telegram_id(
    session: AsyncSession, telegram_id: int
) -> User | None:
    """جستجوی کاربر بر اساس شناسه تلگرام."""
    return await session.get(User, telegram_id)
