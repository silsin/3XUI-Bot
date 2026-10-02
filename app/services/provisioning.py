"""ساخت/تمدید سرویس و کنترل سهمیه مشترک روی چند inbound (چند پروتکل)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

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

# پیشوند تگ پنل در email کلاینت‌های چندپنلی: "...-p{panel_id}-i{inbound}"
_PANEL_TAG = "-p"


def _panel_tag(panel_id: int | None) -> str:
    return f"{_PANEL_TAG}{panel_id}" if panel_id else ""


def panel_id_from_email(email: str) -> int | None:
    """استخراج شناسه پنل از تگ داخل email؛ اگر تگ نباشد None (پنل پیش‌فرض)."""
    marker = f"{_PANEL_TAG}"
    idx = str(email or "").rfind(marker)
    if idx < 0:
        return None
    tail = str(email)[idx + len(marker):]
    digits = ""
    for ch in tail:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None


async def resolve_inbounds(
    session: AsyncSession, fallback: int
) -> list[tuple[int | None, int]]:
    """فهرست (panel_id, inbound_id)؛ خالی یعنی از inbound پیش‌فرض.

    فرمت تنظیم: "4,6" (پنل پیش‌فرض) یا "1:4,2:6" (panel_id:inbound_id).
    مقادیر نامعتبر نادیده گرفته می‌شوند.
    """
    raw = await cfg.get(session, S_MULTI_INBOUNDS, "")
    pairs: list[tuple[int | None, int]] = []
    seen: set[tuple[Any, ...]] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        panel_id: int | None = None
        inbound_part = part
        if ":" in part:
            left, right = part.split(":", 1)
            if left.isdigit() and right.isdigit():
                panel_id = int(left)
                inbound_part = right
            else:
                continue
        elif not part.isdigit():
            continue
        key = (panel_id, int(inbound_part))
        if key not in seen:
            seen.add(key)
            pairs.append((panel_id, int(inbound_part)))
    return pairs or [(None, fallback)]


async def _provider_for(
    session: AsyncSession, panel_id: int | None, fallback_provider: Any = None
) -> tuple[Any, int | None]:
    """کلاینت پنل مناسب برای یک inbound؛ panel_id تهی یعنی پنل پیش‌فرض.

    خروجی: (provider, panel_id_resolved). panel_id_resolved برای تگ‌کردن
    email استفاده می‌شود؛ برای پنل پیش‌فرض None برمی‌گرداند تا email
    کلاینت‌های قدیمی دست‌نخورده بماند.
    """
    from app.services import panel_service as pservice

    if panel_id is None:
        if fallback_provider is not None:
            return fallback_provider, None
        return get_provider(), None
    panel = await pservice.get_panel(session, panel_id)
    if panel is None or not panel.is_active:
        raise VpnError(f"پنل {panel_id} یافت نشد یا غیرفعال است")
    return pservice.get_provider_for_panel(panel), panel.id


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
    """روی همه inboundهای پیکربندی‌شده (هر کدام روی پنل خودش) کلاینت می‌سازد."""
    default_provider = get_provider()
    inbounds = await resolve_inbounds(session, inbound_id)

    base = f"{user.id}-{'trial' if is_trial else 'srv'}-{secrets.token_hex(3)}"
    sub_id = secrets.token_hex(8)

    created: list = []
    for panel_id, inb in inbounds:
        email = ""
        try:
            # هر کلاینت روی پنل خودش ساخته می‌شود؛ خطای یک پنل نباید
            # کل خرید را متوقف کند (زیرا همینجا ممکن است رها شود).
            provider, resolved_pid = await _provider_for(
                session, panel_id, fallback_provider=default_provider
            )
            email = f"{base}{_panel_tag(resolved_pid)}-i{inb}"
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
            logger.error(
                "create_client failed on panel %s inbound %s: %s",
                panel_id if panel_id is not None else "default",
                inb,
                exc,
            )
        except Exception:  # noqa: BLE001 — هیچ خطای غیرمنتظره‌ای خرید را نگه ندارد
            logger.exception(
                "unexpected create failure on panel %s inbound %s (email=%s)",
                panel_id,
                inb,
                email,
            )

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
    reset_traffic: bool = True,  # ← برای renewal، حجم را reset کن
) -> Service:
    """تمدید همه کلاینت‌های سرویس روی همان inboundها (هر کدام روی پنل خودش)."""
    service = await _load_service(session, service.id) or service
    reset = service.status is not ServiceStatus.ACTIVE or reset_traffic

    for client in service.clients:
        provider, _ = await _provider_for(
            session, panel_id_from_email(client.email)
        )
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
        service.traffic_mb = add_traffic_mb  # ← حجم را reset کن (نه اضافه کن)
    service.status = ServiceStatus.ACTIVE
    service.expiry_notified = False
    if title:
        service.title = title
    await session.commit()
    await session.refresh(service)
    return service


async def delete_service(session: AsyncSession, service: Service) -> None:
    """حذف همه کلاینت‌های سرویس از پنل و دیتابیس."""
    service = await _load_service(session, service.id) or service
    for client in service.clients:
        provider, _ = await _provider_for(
            session, panel_id_from_email(client.email)
        )
        try:
            await provider.delete_client(client.inbound_id, client.client_uuid)
        except VpnError as exc:
            logger.warning("delete failed for %s: %s", client.email, exc)
    await session.delete(service)
    await session.commit()


async def regenerate_links(session: AsyncSession, service_id: int | None = None) -> int:
    """لینک همه کلاینت‌ها را بر اساس host فعلی (دامنه) بازسازی می‌کند.
    
    Args:
        session: دیتابیس سشن
        service_id: اگر مشخص شود، فقط کلاینت‌های آن سرویس بازسازی می‌شوند
    """
    from app.services import panel_service as pservice
    
    default_provider = get_provider()
    
    # List all panels in database
    all_panels = await pservice.list_panels(session)
    logger.info("regenerate_links: found %d panels in database", len(all_panels))
    for p in all_panels:
        logger.info("  Panel %d: %s (%s), active=%s, url=%s...", 
                   p.id, p.title, p.variant, p.is_active, 
                   p.base_url[:60] if p.base_url else "None")
    
    # Find an active panel to use as default
    active_panels = [p for p in all_panels if p.is_active]
    if active_panels:
        default_panel = active_panels[0]
        default_panel_provider = pservice.get_provider_for_panel(default_panel)
        logger.info("Using active panel %d (%s) as default provider", default_panel.id, default_panel.title)
    elif all_panels:
        default_panel = all_panels[0]  # First panel as fallback
        default_panel_provider = pservice.get_provider_for_panel(default_panel)
        logger.warning("No active panels found, using inactive panel %d (%s) as fallback", default_panel.id, default_panel.title)
    else:
        default_panel_provider = None
        logger.info("No panels in database, using .env provider")
    
    stmt = select(ServiceClient).order_by(ServiceClient.id)
    if service_id:
        stmt = stmt.where(ServiceClient.service_id == service_id)
    
    clients = list((await session.execute(stmt)).scalars().all())
    
    if not clients:
        return 0
    
    logger.info("Found %d clients to process", len(clients))
    
    changed = 0
    primary_by_service: dict[int, str] = {}
    
    # Cache providers for different panels
    panel_providers: dict[int, Any] = {}
    
    async def get_panel_provider(pid: int) -> Any:
        if pid not in panel_providers:
            panel = await pservice.get_panel(session, pid)
            if panel and panel.is_active:
                panel_providers[pid] = pservice.get_provider_for_panel(panel)
                logger.info("Created provider for panel %d: %s", pid, panel.title)
            else:
                panel_providers[pid] = None
                logger.warning("Panel %d not found or inactive", pid)
        return panel_providers[pid]
    
    for c in clients:
        # Determine which provider to use based on panel tag in email
        pid = panel_id_from_email(c.email)
        
        logger.info("Processing client %d: email=%s, pid=%s", c.id, c.email[:60] if c.email else "None", pid)
        
        if pid is not None:
            # Client belongs to a specific panel
            provider = await get_panel_provider(pid)
            if provider is None:
                logger.warning("Panel %d not found/active, falling back to default panel", pid)
                if default_panel_provider:
                    provider = default_panel_provider
                elif all_panels:
                    provider = default_provider
                else:
                    logger.error("No providers available, skipping client %d", c.id)
                    continue
        elif default_panel_provider:
            # Use first panel from database as default
            provider = default_panel_provider
            logger.info("No panel tag, using default panel provider")
        else:
            # Use .env provider
            provider = default_provider
            logger.info("No panels in DB, using .env provider")
        
        try:
            link = await provider.build_client_link(
                c.inbound_id, c.client_uuid, c.email
            )
            logger.info("Built link for client %d: %s...", c.id, link[:60] if link else "None")
        except VpnError as exc:
            logger.warning("Failed to build link for client %d (%s): %s", 
                          c.id, c.email[:30] if c.email else "None", exc)
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
    logger.info("regenerate_links complete: changed=%d out of %d clients", changed, len(clients))
    return changed


async def _usage_for(
    session: AsyncSession,
    service: Service,
    usage_map: dict | None,
) -> tuple[dict[str, Any], Any]:
    """مصرف همه کلاینت‌های سرویس را از پنل‌های مربوطه جمع می‌کند.

    usage_map ورودی فقط برای پنل پیش‌فرض معتبر است؛ برای کلاینت‌های
    چندپنلی به‌صورت جداگانه خوانده می‌شود.
    """
    provider = get_provider()
    merged: dict[str, Any] = dict(usage_map) if usage_map else {}
    if usage_map is None:
        try:
            merged.update(await provider.get_all_usage())
        except VpnError as exc:
            logger.warning("usage fetch failed: %s", exc)

    from app.services import panel_service as pservice

    other_panels: dict[int, Any] = {}

    async def _panel_provider(pid: int) -> Any | None:
        if pid not in other_panels:
            panel = await pservice.get_panel(session, pid)
            if panel is None or not panel.is_active:
                return None
            other_panels[pid] = pservice.get_provider_for_panel(panel)
        return other_panels[pid]

    for client in service.clients:
        pid = panel_id_from_email(client.email)
        if pid is None or client.email in merged:
            continue
        pvd = await _panel_provider(pid)
        if pvd is None:
            continue
        try:
            merged[client.email] = await pvd.get_usage(client.email)
        except VpnError as exc:
            logger.warning("usage fetch failed for %s: %s", client.email, exc)
    return merged, provider


async def sync_service(
    session: AsyncSession, service: Service, usage_map: dict | None = None
) -> Service:
    """مصرف کلاینت‌ها را جمع می‌کند؛ در صورت عبور از سهمیه یا انقضا همه را قطع می‌کند."""
    service = await _load_service(session, service.id) or service
    usage_map, provider = await _usage_for(session, service, usage_map)

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
                cprovider, _ = await _provider_for(
                    session, panel_id_from_email(client.email),
                    fallback_provider=provider,
                )
                try:
                    await cprovider.set_enabled(
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

    default_provider = get_provider()
    inbounds = await resolve_inbounds(session, parent.inbound_id)

    # ── کاهش سهمیه سرویس والد روی پنل ──────────────────────────
    new_parent_mb = max(0, parent.traffic_mb - allocated_mb)
    for client in parent.clients:
        cprovider, _ = await _provider_for(
            session,
            panel_id_from_email(client.email),
            fallback_provider=default_provider,
        )
        try:
            await cprovider.set_quota_mb(
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
    for panel_id, inb in inbounds:
        cprovider, resolved_pid = await _provider_for(
            session, panel_id, fallback_provider=default_provider
        )
        email = f"{base}{_panel_tag(resolved_pid)}-i{inb}"
        try:
            res = await cprovider.create_client(
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
            logger.error(
                "split create_client failed on panel %s inbound %s: %s",
                resolved_pid if resolved_pid is not None else "default",
                inb,
                exc,
            )

    if not created:
        # برگرداندن سهمیه والد در صورت شکست
        parent.traffic_mb = parent.traffic_mb + allocated_mb
        for client in parent.clients:
            cprovider, _ = await _provider_for(
                session,
                panel_id_from_email(client.email),
                fallback_provider=default_provider,
            )
            try:
                await cprovider.set_quota_mb(
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
