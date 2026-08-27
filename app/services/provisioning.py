"""ساخت/تمدید سرویس: پل بین سفارش‌های ربات و پنل 3x-ui."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, Service, ServiceStatus, TrialClaim, User
from app.services import settings_service as cfg
from app.services.vpn import VpnError, get_provider
from app.texts import S_TRIAL_GB, S_TRIAL_DAYS, S_TRIAL_INBOUND

logger = logging.getLogger(__name__)


def make_email(user_id: int, tag: str = "") -> str:
    """ایمیل (شناسه) یکتا برای کلاینت پنل."""
    suffix = secrets.token_hex(3)
    parts = [str(user_id)]
    if tag:
        parts.append(tag)
    parts.append(suffix)
    return "-".join(parts)


async def create_service(
    session: AsyncSession,
    *,
    user: User,
    days: int,
    traffic_gb: int,
    inbound_id: int,
    title: str,
    device_limit: int = 0,
    is_trial: bool = False,
    order: Order | None = None,
) -> Service:
    """روی پنل کلاینت می‌سازد و سرویس را در دیتابیس ثبت می‌کند."""
    email = make_email(user.id, "trial" if is_trial else "srv")
    provider = get_provider()

    result = await provider.create_client(
        inbound_id=inbound_id,
        email=email,
        days=days,
        traffic_gb=traffic_gb,
        device_limit=device_limit,
        telegram_id=user.id,
    )

    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=days) if days > 0 else None
    )
    service = Service(
        user_id=user.id,
        order_id=order.id if order else None,
        title=title,
        inbound_id=inbound_id,
        client_uuid=result.uuid,
        email=result.email,
        sub_id=result.sub_id,
        config_link=result.config_link,
        sub_link=result.sub_link,
        traffic_gb=traffic_gb,
        expires_at=expires_at,
        is_trial=is_trial,
        status=ServiceStatus.ACTIVE,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    logger.info("service %s created for user %s", service.id, user.id)
    return service


async def grant_trial(session: AsyncSession, user: User) -> Service:
    """تست رایگان - فقط یک‌بار برای هر کاربر."""
    days = await cfg.get_int(session, S_TRIAL_DAYS, 1)
    traffic_gb = await cfg.get_int(session, S_TRIAL_GB, 1)
    inbound_id = await cfg.get_int(session, S_TRIAL_INBOUND, 1)

    service = await create_service(
        session,
        user=user,
        days=days,
        traffic_gb=traffic_gb,
        inbound_id=inbound_id,
        title=f"تست رایگان {days} روزه",
        device_limit=1,
        is_trial=True,
    )

    user.trial_used = True
    session.add(TrialClaim(user_id=user.id, service_id=service.id))
    await session.commit()
    return service


async def renew_service(
    session: AsyncSession,
    *,
    service: Service,
    add_days: int,
    add_traffic_gb: int,
    title: str = "",
) -> Service:
    """تمدید سرویس موجود روی همان کلاینت پنل."""
    provider = get_provider()
    reset = service.status is ServiceStatus.EXPIRED

    await provider.extend_client(
        inbound_id=service.inbound_id,
        client_uuid=service.client_uuid,
        email=service.email,
        add_days=add_days,
        add_traffic_gb=add_traffic_gb,
        reset_traffic=reset,
    )

    now = datetime.now(timezone.utc)
    current = service.expires_at
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    base = current if current and current > now else now
    service.expires_at = base + timedelta(days=add_days) if add_days > 0 else None

    if add_traffic_gb > 0:
        service.traffic_gb = (
            add_traffic_gb if reset else service.traffic_gb + add_traffic_gb
        )
    service.status = ServiceStatus.ACTIVE
    service.expiry_notified = False
    if title:
        service.title = title
    await session.commit()
    await session.refresh(service)
    return service


async def sync_usage(session: AsyncSession, service: Service) -> Service:
    """مصرف را از پنل می‌خواند و در دیتابیس به‌روزرسانی می‌کند."""
    try:
        usage = await get_provider().get_usage(service.email)
    except VpnError as exc:
        logger.warning("usage sync failed for %s: %s", service.email, exc)
        return service

    if not usage.found:
        return service

    service.used_bytes = usage.used_bytes
    if usage.expiry_ms > 0:
        service.expires_at = datetime.fromtimestamp(
            usage.expiry_ms / 1000, tz=timezone.utc
        )
    now = datetime.now(timezone.utc)
    expires = service.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires is not None and expires <= now:
        service.status = ServiceStatus.EXPIRED
    elif not usage.enable:
        service.status = ServiceStatus.DISABLED
    else:
        service.status = ServiceStatus.ACTIVE
    await session.commit()
    return service
