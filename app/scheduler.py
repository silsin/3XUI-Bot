"""کارهای زمان‌بندی‌شده: همگام‌سازی مصرف و یادآوری انقضا."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.db.models import Service, ServiceStatus
from app.db.session import get_sessionmaker
from app.services import provisioning
from app.utils.formatting import days_left, days_left_text

logger = logging.getLogger(__name__)

REMIND_WITHIN_DAYS = 3


async def sync_and_remind(bot: Bot) -> None:
    """مصرف را جمع می‌زند، سهمیه/انقضا را اعمال و درباره انقضای نزدیک هشدار می‌دهد."""
    sessionmaker = get_sessionmaker()
    from app.services.vpn import get_provider

    async with sessionmaker() as session:
        services = list(
            (
                await session.execute(
                    select(Service).where(Service.status != ServiceStatus.EXPIRED)
                )
            ).scalars().all()
        )
        if not services:
            return

        # یک بار همه مصرف‌ها را می‌گیریم و بین سرویس‌ها به اشتراک می‌گذاریم
        try:
            usage_map = await get_provider().get_all_usage()
        except Exception:  # noqa: BLE001
            logger.exception("bulk usage fetch failed")
            usage_map = {}

        for service in services:
            try:
                service = await provisioning.sync_service(session, service, usage_map)
            except Exception:  # noqa: BLE001
                logger.exception("sync failed for service %s", service.id)
                continue

            if service.expires_at is None or service.status != ServiceStatus.ACTIVE:
                continue
            remaining = days_left(service.expires_at)
            if 0 < remaining <= REMIND_WITHIN_DAYS and not service.expiry_notified:
                try:
                    await bot.send_message(
                        service.user_id,
                        f"⏰ سرویس «{service.title}» شما تا "
                        f"<b>{days_left_text(service.expires_at)}</b> دیگر منقضی می‌شود.\n"
                        "برای جلوگیری از قطعی، از «تمدید سرویس» استفاده کنید.",
                    )
                    service.expiry_notified = True
                    await session.commit()
                except Exception:  # noqa: BLE001
                    logger.info("could not remind user %s", service.user_id)


def setup_scheduler(bot: Bot, timezone_name: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone_name)
    scheduler.add_job(
        sync_and_remind,
        trigger="interval",
        minutes=10,
        args=(bot,),
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1),
        id="sync_and_remind",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
