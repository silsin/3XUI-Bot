"""ساخت/تمدید سرویس و کنترل سهمیه مشترک روی چند inbound (چند پروتکل)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Order,
    Service,
    ServiceClient,
    ServiceSplit,
    ServiceStatus,
    TrialClaim,
    User,
)
from app.services import settings_service as cfg
from app.services.vpn import VpnError, get_provider
from app.texts import (
    S_MULTI_INBOUNDS,
    S_TRIAL_DAYS,
    S_TRIAL_INBOUND,
    S_TRIAL_MB,
)

logger = logging.getLogger(__name__)

MB = 1024 ** 2


async def resolve_inbounds(session: AsyncSession, fallback: int) -> list[int]:
    """فهرست inboundهای پیکربندی‌شده؛ اگر خالی بود از inbound پیش‌فرض استفاده می‌شود."""
    raw = await cfg.get(session, S_MULTI_INBOUNDS, "")
    ids: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            n = int(part)
            if n not in ids:
                ids.append(n)
    return ids or [fallback]


async def _load_service(session: AsyncSession, service_id: int) -> Service | None:
    return (
        await session.execute(
            select(Service)
            .where(Service.id == service_id)
            .options(selectinload(Service.clients))
        )
    ).scalar_one_or_none()


async def create_service(
    session: AsyncSession,
    *,
    user: User,
    days: int,
    traffic_mb: int,
    inbound_id: int,
    title: str,
    device_limit: int = 0,
    is_trial: bool = False,
    order: Order | None = None,
) -> Service:
    """روی همه inboundهای پیکربندی‌شده کلاینت می‌سازد (هویت و سهمیه مشترک)."""
    provider = get_provider()
    inbounds = await resolve_inbounds(session, inbound_id)

    base = f"{user.id}-{'trial' if is_trial else 'srv'}-{secrets.token_hex(3)}"
    sub_id = secrets.token_hex(8)

    created: list = []
    for inb in inbounds:
        email = f"{base}-i{inb}"
        try:
            res = await provider.create_client(
                inbound_id=inb,
                email=email,
                days=days,
                traffic_mb=traffic_mb,
                device_limit=device_limit,
                telegram_id=user.id,
                sub_id=sub_id,
            )
            created.append(res)
        except VpnError as exc:
            logger.error("create_client failed on inbound %s: %s", inb, exc)

    if not created:
        raise VpnError("هیچ inboundی قابل ساخت نبود")

    primary = created[0]
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=days) if days > 0 else None
    )
    service = Service(
        user_id=user.id,
        order_id=order.id if order else None,
        title=title,
        inbound_id=primary.inbound_id,
        client_uuid=primary.uuid,
        email=primary.email,
        sub_id=sub_id,
        config_link=primary.config_link,
        sub_link=primary.sub_link,
        traffic_mb=traffic_mb,
        expires_at=expires_at,
        is_trial=is_trial,
        status=ServiceStatus.ACTIVE,
    )
    session.add(service)
    await session.flush()

    for res in created:
        session.add(
            ServiceClient(
                service_id=service.id,
                inbound_id=res.inbound_id,
                protocol=res.protocol,
                label=(res.protocol or "config").upper(),
                client_uuid=res.uuid,
                email=res.email,
                config_link=res.config_link,
                enabled=True,
            )
        )
    await session.commit()
    await session.refresh(service)
    logger.info(
        "service %s created for user %s across %d inbound(s)",
        service.id, user.id, len(created),
    )
    return service


async def grant_trial(session: AsyncSession, user: User) -> Service:
    """تست رایگان - فقط یک‌بار برای هر کاربر."""
    days = await cfg.get_int(session, S_TRIAL_DAYS, 1)
    traffic_mb = await cfg.get_int(session, S_TRIAL_MB, 1024)
    inbound_id = await cfg.get_int(session, S_TRIAL_INBOUND, 1)

    service = await create_service(
        session,
        user=user,
        days=days,
        traffic_mb=traffic_mb,
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
    add_traffic_mb: int,
    title: str = "",
) -> Service:
    """تمدید همه کلاینت‌های سرویس روی همان inboundها."""
    provider = get_provider()
    service = await _load_service(session, service.id) or service
    reset = service.status is not ServiceStatus.ACTIVE

    for client in service.clients:
        try:
            await provider.extend_client(
                inbound_id=client.inbound_id,
                client_uuid=client.client_uuid,
                email=client.email,
                add_days=add_days,
                add_traffic_mb=add_traffic_mb,
                reset_traffic=reset,
            )
            client.enabled = True
        except VpnError as exc:
            logger.error("extend failed for %s: %s", client.email, exc)

    now = datetime.now(timezone.utc)
    current = service.expires_at
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    base = current if current and current > now else now
    service.expires_at = base + timedelta(days=add_days) if add_days > 0 else None

    if add_traffic_mb > 0:
        service.traffic_mb = (
            add_traffic_mb if reset else service.traffic_mb + add_traffic_mb
        )
    service.status = ServiceStatus.ACTIVE
    service.expiry_notified = False
    if title:
        service.title = title
    await session.commit()
    await session.refresh(service)
    return service


async def delete_service(session: AsyncSession, service: Service) -> None:
    """حذف همه کلاینت‌های سرویس از پنل و دیتابیس."""
    provider = get_provider()
    service = await _load_service(session, service.id) or service
    for client in service.clients:
        try:
            await provider.delete_client(client.inbound_id, client.client_uuid)
        except VpnError as exc:
            logger.warning("delete failed for %s: %s", client.email, exc)
    await session.delete(service)
    await session.commit()


async def regenerate_links(session: AsyncSession) -> int:
    """لینک همه کلاینت‌ها را بر اساس host فعلی (دامنه) بازسازی می‌کند."""
    provider = get_provider()
    clients = list(
        (
            await session.execute(
                select(ServiceClient).order_by(ServiceClient.id)
            )
        ).scalars().all()
    )
    changed = 0
    primary_by_service: dict[int, str] = {}
    for c in clients:
        try:
            link = await provider.build_client_link(
                c.inbound_id, c.client_uuid, c.email
            )
        except VpnError:
            continue
        if link and link != c.config_link:
            c.config_link = link
            changed += 1
        primary_by_service.setdefault(c.service_id, c.config_link)

    # لینک اصلی هر سرویس را هم به‌روزرسانی کن
    for service_id, link in primary_by_service.items():
        svc = await session.get(Service, service_id)
        if svc is not None and link:
            svc.config_link = link

    await session.commit()
    return changed


async def sync_service(
    session: AsyncSession, service: Service, usage_map: dict | None = None
) -> Service:
    """مصرف کلاینت‌ها را جمع می‌کند؛ در صورت عبور از سهمیه یا انقضا همه را قطع می‌کند."""
    provider = get_provider()
    service = await _load_service(session, service.id) or service

    if usage_map is None:
        try:
            usage_map = await provider.get_all_usage()
        except VpnError as exc:
            logger.warning("usage fetch failed: %s", exc)
            return service

    total_used = 0
    latest_expiry_ms = 0
    for client in service.clients:
        info = usage_map.get(client.email)
        if info is not None:
            client.used_bytes = info.used_bytes
            total_used += info.used_bytes
            latest_expiry_ms = max(latest_expiry_ms, info.expiry_ms)

    service.used_bytes = total_used
    if latest_expiry_ms > 0:
        service.expires_at = datetime.fromtimestamp(
            latest_expiry_ms / 1000, tz=timezone.utc
        )

    now = datetime.now(timezone.utc)
    expires = service.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    is_expired = expires is not None and expires <= now
    over_quota = service.traffic_mb > 0 and total_used >= service.traffic_mb * MB

    if is_expired or over_quota:
        for client in service.clients:
            if client.enabled:
                try:
                    await provider.set_enabled(
                        client.inbound_id, client.client_uuid, client.email, False
                    )
                except VpnError:
                    pass
                client.enabled = False
        service.status = (
            ServiceStatus.EXPIRED if is_expired else ServiceStatus.DISABLED
        )
    else:
        service.status = ServiceStatus.ACTIVE

    await session.commit()
    return service


# سازگاری با کد قدیمی
sync_usage = sync_service


async def split_service(
    session: AsyncSession,
    *,
    parent: Service,
    allocated_mb: int,
    recipient: User,
    title: str = "",
) -> Service:
    """از سرویس والد (parent) حجم جدا می‌کند و سرویس فرزند (child) می‌سازد.

    - سهمیه‌ی parent به‌اندازه allocated_mb کاهش می‌یابد (روی پنل).
    - یک سرویس جدید با همان تاریخ انقضا برای recipient ساخته می‌شود.
    - رابطه در ServiceSplit ثبت می‌شود.
    """
    if allocated_mb <= 0:
        raise VpnError("حجم باید بزرگ‌تر از صفر باشد.")

    # بارگذاری با کلاینت‌ها
    parent = await _load_service(session, parent.id) or parent

    if parent.traffic_mb > 0 and allocated_mb > parent.traffic_mb:
        raise VpnError(
            f"حجم درخواستی ({allocated_mb} MB) از موجودی سرویس "
            f"({parent.traffic_mb} MB) بیشتر است."
        )

    provider = get_provider()
    inbounds = await resolve_inbounds(session, parent.inbound_id)

    # ── کاهش سهمیه سرویس والد روی پنل ──────────────────────────
    new_parent_mb = max(0, parent.traffic_mb - allocated_mb)
    for client in parent.clients:
        try:
            await provider.set_quota_mb(
                inbound_id=client.inbound_id,
                client_uuid=client.client_uuid,
                email=client.email,
                traffic_mb=new_parent_mb,
            )
        except VpnError as exc:
            logger.warning("reduce quota failed for %s: %s", client.email, exc)

    parent.traffic_mb = new_parent_mb
    await session.flush()

    # ── ساخت سرویس فرزند ──────────────────────────────────────────
    child_title = title or f"زیرسرویس {allocated_mb} MB"
    # محاسبه روزهای باقی‌مانده از سرویس والد
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if parent.expires_at is not None:
        exp = parent.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        remaining_days = max(0, (exp - now).days)
    else:
        remaining_days = 0  # نامحدود → 0 به معنی نامحدود در create_service

    base = f"{recipient.id}-split-{secrets.token_hex(3)}"
    sub_id = secrets.token_hex(8)

    created: list = []
    for inb in inbounds:
        email = f"{base}-i{inb}"
        try:
            res = await provider.create_client(
                inbound_id=inb,
                email=email,
                days=remaining_days,
                traffic_mb=allocated_mb,
                device_limit=0,
                telegram_id=recipient.id,
                sub_id=sub_id,
            )
            created.append(res)
        except VpnError as exc:
            logger.error("split create_client failed on inbound %s: %s", inb, exc)

    if not created:
        # برگرداندن سهمیه والد در صورت شکست
        parent.traffic_mb = parent.traffic_mb + allocated_mb
        for client in parent.clients:
            try:
                await provider.set_quota_mb(
                    inbound_id=client.inbound_id,
                    client_uuid=client.client_uuid,
                    email=client.email,
                    traffic_mb=parent.traffic_mb,
                )
            except VpnError:
                pass
        await session.flush()
        raise VpnError("ساخت سرویس فرزند روی پنل ناموفق بود.")

    primary = created[0]
    child = Service(
        user_id=recipient.id,
        order_id=None,
        title=child_title,
        inbound_id=primary.inbound_id,
        client_uuid=primary.uuid,
        email=primary.email,
        sub_id=sub_id,
        config_link=primary.config_link,
        sub_link=primary.sub_link,
        traffic_mb=allocated_mb,
        expires_at=parent.expires_at,   # همان تاریخ انقضای والد
        is_trial=False,
        status=ServiceStatus.ACTIVE,
    )
    session.add(child)
    await session.flush()

    for res in created:
        session.add(
            ServiceClient(
                service_id=child.id,
                inbound_id=res.inbound_id,
                protocol=res.protocol,
                label=(res.protocol or "config").upper(),
                client_uuid=res.uuid,
                email=res.email,
                config_link=res.config_link,
                enabled=True,
            )
        )

    # ثبت رابطه split
    session.add(
        ServiceSplit(
            parent_service_id=parent.id,
            child_service_id=child.id,
            allocated_mb=allocated_mb,
            recipient_user_id=recipient.id,
        )
    )

    await session.commit()
    await session.refresh(child)
    logger.info(
        "split: parent=%s -%dMB → child=%s for user=%s",
        parent.id, allocated_mb, child.id, recipient.id,
    )
    return child
