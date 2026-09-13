"""سرویس لاگ فعالیت کاربران."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserActivity


async def log_activity(
    session: AsyncSession,
    user_id: int,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    """ثبت یک فعالیت کاربر."""
    import json
    
    details_str = json.dumps(details, ensure_ascii=False) if details else None
    activity = UserActivity(
        user_id=user_id,
        action=action,
        details=details_str,
    )
    session.add(activity)
    await session.commit()


async def get_user_activities(
    session: AsyncSession,
    user_id: int,
    limit: int = 50,
) -> list[UserActivity]:
    """دریافت فعالیت‌های یک کاربر."""
    stmt = (
        select(UserActivity)
        .where(UserActivity.user_id == user_id)
        .order_by(desc(UserActivity.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_recent_activities(
    session: AsyncSession,
    limit: int = 100,
) -> list[UserActivity]:
    """دریافت最近的 فعالیت‌ها."""
    stmt = (
        select(UserActivity)
        .order_by(desc(UserActivity.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_activity_stats(
    session: AsyncSession,
    days: int = 7,
) -> dict[str, Any]:
    """آمار فعالیت‌ها در N روز گذشته."""
    from datetime import timezone as tz
    
    since = datetime.now(tz.utc) - timedelta(days=days)
    
    # تعداد کل فعالیت‌ها
    total_stmt = select(func.count(UserActivity.id)).where(
        UserActivity.created_at >= since
    )
    total_result = await session.execute(total_stmt)
    total = total_result.scalar() or 0
    
    # تعداد کاربران فعال
    active_users_stmt = select(func.count(func.distinct(UserActivity.user_id))).where(
        UserActivity.created_at >= since
    )
    active_users_result = await session.execute(active_users_stmt)
    active_users = active_users_result.scalar() or 0
    
    # شمارش بر اساس نوع فعالیت
    action_counts_stmt = (
        select(UserActivity.action, func.count(UserActivity.id))
        .where(UserActivity.created_at >= since)
        .group_by(UserActivity.action)
        .order_by(desc(func.count(UserActivity.id)))
    )
    action_result = await session.execute(action_counts_stmt)
    action_counts = {row[0]: row[1] for row in action_result.fetchall()}
    
    return {
        "total": total,
        "active_users": active_users,
        "action_counts": action_counts,
        "days": days,
    }


async def get_user_activity_summary(
    session: AsyncSession,
    user_id: int,
    days: int = 30,
) -> dict[str, Any]:
    """خلاصه فعالیت‌های یک کاربر."""
    from datetime import timezone as tz
    
    since = datetime.now(tz.utc) - timedelta(days=days)
    
    # تعداد کل فعالیت‌ها
    total_stmt = select(func.count(UserActivity.id)).where(
        and_(
            UserActivity.user_id == user_id,
            UserActivity.created_at >= since,
        )
    )
    total_result = await session.execute(total_stmt)
    total = total_result.scalar() or 0
    
    # شمارش بر اساس نوع فعالیت
    action_counts_stmt = (
        select(UserActivity.action, func.count(UserActivity.id))
        .where(
            and_(
                UserActivity.user_id == user_id,
                UserActivity.created_at >= since,
            )
        )
        .group_by(UserActivity.action)
        .order_by(desc(func.count(UserActivity.id)))
    )
    action_result = await session.execute(action_counts_stmt)
    action_counts = {row[0]: row[1] for row in action_result.fetchall()}
    
    # آخرین فعالیت
    last_stmt = (
        select(UserActivity)
        .where(UserActivity.user_id == user_id)
        .order_by(desc(UserActivity.created_at))
        .limit(1)
    )
    last_result = await session.execute(last_stmt)
    last_activity = last_result.scalar_one_or_none()
    
    return {
        "total": total,
        "action_counts": action_counts,
        "last_activity": last_activity.action if last_activity else None,
        "last_activity_at": last_activity.created_at if last_activity else None,
        "days": days,
    }


# نام فعالیت‌های قابل ثبت
class Actions:
    # منو و ناوبری
    START = "start"
    MENU = "menu"
    
    # خرید
    VIEW_PLANS = "view_plans"
    VIEW_DURATIONS = "view_durations"
    VIEW_PACKAGES = "view_packages"
    SELECT_PACKAGE = "select_package"
    INITIATE_BUY = "initiate_buy"
    VIEW_ORDERS = "view_orders"
    
    # سرویس‌ها
    VIEW_SERVICES = "view_services"
    VIEW_CONFIG = "view_config"
    COPY_LINK = "copy_link"
    REGEN_LINKS = "regen_links"
    
    # امتیاز
    VIEW_POINTS = "view_points"
    REDEEM_POINTS = "redeem_points"
    INVITE = "invite"
    
    # تست رایگان
    TRIAL = "trial"
    
    # متفرقه
    GUIDE = "guide"
    SUPPORT = "support"