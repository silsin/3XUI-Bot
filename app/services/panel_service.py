"""مدیریت پنل‌ها و اینباندهای ثبت‌شده در دیتابیس.

این سرویس جایگزین خواندن تنها یک پنل از .env است. پنل‌ها از رابط ادمین
ساخته می‌شوند و هر کدام یک VpnProvider مستقل دارند.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Panel, PanelInbound
from app.services.vpn import VpnError

logger = logging.getLogger(__name__)

# هر پنل یک کلاینت HTTP مستقل دارد تا بین پنل‌ها تداخل نشود
_providers: dict[int, Any] = {}

# نسخه‌های پشتیبانی‌شده
VARIANTS = {
    "xui3": "3x-ui نسخه 3 (توکن)",
    "legacy": "x-ui 1.x (vaxilu)",
    "panel": "3x-ui کلاسیک",
}


def settings_for_panel(panel: Panel) -> Settings:
    """یک Settings منحصربه‌فرد از روی رکورد پنل می‌سازد.

    Settings یک pydantic BaseSettings است؛ مقدارهای پایه را نگه می‌داریم
    و فقط فیلدهای مربوط به پنل را جایگزین می‌کنیم.
    """
    base = get_settings()
    return base.model_copy(
        update={
            "xui_variant": panel.variant,
            "xui_base_url": panel.base_url,
            "xui_web_base_path": panel.web_base_path,
            "xui_api_token": panel.api_token,
            "xui_username": panel.username,
            "xui_password": panel.password,
            "xui_node_host": panel.node_host,
            "xui_sub_base_url": panel.sub_base_url,
            "xui_verify_ssl": panel.verify_ssl,
        }
    )


def get_provider_for_panel(panel: Panel):
    """کلاینت پنل مورد نظر (با کش)؛ خارج از کش global در vpn/__init__."""
    cached = _providers.get(panel.id)
    if cached is not None:
        return cached
    from app.services.vpn import build_provider_for

    client = build_provider_for(settings_for_panel(panel))
    _providers[panel.id] = client
    return client


def invalidate_cache(panel_id: int | None = None) -> None:
    """کش پنل را پاک کند (پس از ویرایش یا حذف)."""
    if panel_id is None:
        _providers.clear()
    else:
        _providers.pop(panel_id, None)


async def close_all() -> None:
    for pid, client in list(_providers.items()):
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            logger.warning("closing provider %s failed", pid)
    _providers.clear()


# ---------- پنل ----------


async def list_panels(session: AsyncSession) -> list[Panel]:
    rows = (
        await session.execute(select(Panel).order_by(Panel.sort_order, Panel.id))
    ).scalars().all()
    return list(rows)


async def get_panel(session: AsyncSession, panel_id: int) -> Panel | None:
    return await session.get(Panel, panel_id)


async def add_panel(session: AsyncSession, **fields: Any) -> Panel:
    panel = Panel(**fields)
    session.add(panel)
    await session.commit()
    await session.refresh(panel)
    invalidate_cache(panel.id)
    logger.info("panel %s created (variant=%s)", panel.id, panel.variant)
    return panel


async def update_panel(session: AsyncSession, panel: Panel, **changes: Any) -> Panel:
    for key, value in changes.items():
        setattr(panel, key, value)
    await session.commit()
    await session.refresh(panel)
    invalidate_cache(panel.id)
    return panel


async def delete_panel(session: AsyncSession, panel: Panel) -> None:
    pid = panel.id
    invalidate_cache(pid)
    await session.delete(panel)
    await session.commit()


async def test_panel(session: AsyncSession, panel: Panel) -> None:
    """اتصال را تست می‌کند؛ در صورت خطا VpnError پرتاب می‌کند."""
    try:
        client = get_provider_for_panel(panel)
        await client.ping()
    except VpnError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VpnError(f"{type(exc).__name__}: {exc}") from exc


# ---------- اینباند ----------


async def list_inbounds_of(
    session: AsyncSession, panel_id: int
) -> list[PanelInbound]:
    rows = (
        await session.execute(
            select(PanelInbound)
            .where(PanelInbound.panel_id == panel_id)
            .order_by(PanelInbound.sort_order, PanelInbound.id)
        )
    ).scalars().all()
    return list(rows)

async def register_inbound(
    session: AsyncSession,
    panel: Panel,
    *,
    inbound_id: int,
    remark: str = "",
    protocol: str = "",
    port: int = 0,
    network: str = "",
    security: str = "",
) -> PanelInbound | None:
    """ثبت یک inbound موجود پنل؛ تکراری باشد None برمی‌گرداند."""
    existing = (
        await session.execute(
            select(PanelInbound).where(
                PanelInbound.panel_id == panel.id,
                PanelInbound.inbound_id == inbound_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    row = PanelInbound(
        panel_id=panel.id,
        inbound_id=inbound_id,
        remark=remark,
        protocol=protocol,
        port=port,
        network=network,
        security=security,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("inbound %s registered on panel %s", inbound_id, panel.id)
    return row


async def unregister_inbound(session: AsyncSession, row: PanelInbound) -> None:
    """فقط از ربات حذف می‌کند؛ روی پنل باقی می‌ماند."""
    await session.delete(row)
    await session.commit()


async def sync_inbound_meta(session: AsyncSession, row: PanelInbound) -> None:
    """فیلدها را از وضعیت زنده پنل تازه می‌کند."""
    panel = await session.get(Panel, row.panel_id)
    if panel is None:
        return
    try:
        client = get_provider_for_panel(panel)
        info = await client.get_inbound_info(row.inbound_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sync inbound %s failed: %s", row.inbound_id, exc)
        return
    row.remark = str(info.get("remark") or "")
    row.protocol = str(info.get("protocol") or "")
    row.port = int(info.get("port") or 0)
    row.network = str(info.get("network") or "")
    row.security = str(info.get("security") or "")
    await session.commit()


async def default_panel(session: AsyncSession) -> Panel | None:
    rows = (
        await session.execute(
            select(Panel)
            .where(Panel.is_active.is_(True))
            .order_by(Panel.sort_order, Panel.id)
        )
    ).scalars().all()
    return rows[0] if rows else None


async def ensure_default_from_env(session: AsyncSession) -> Panel | None:
    """اگر هنوز پنلی ثبت نشده، پنل .env را به عنوان اولین پنل درج می‌کند.

    با این کار بعد از بروزرسانی از حالت تک‌پنل به چندپنل، از پنل فعلی
    قفل نمی‌شویم.
    """
    count = (await session.execute(select(Panel.id))).scalars().all()
    if count:
        return None
    base = get_settings()
    if not base.xui_base_url:
        return None
    panel = Panel(
        title="پنل اولیه",
        variant=base.xui_variant,
        base_url=base.xui_base_url,
        web_base_path=base.xui_web_base_path,
        api_token=base.xui_api_token,
        username=base.xui_username,
        password=base.xui_password,
        node_host=base.xui_node_host,
        sub_base_url=base.xui_sub_base_url,
        verify_ssl=base.xui_verify_ssl,
        is_active=True,
        sort_order=0,
    )
    session.add(panel)
    await session.commit()
    await session.refresh(panel)
    logger.info("seeded panel %s from .env", panel.id)
    return panel


__all__ = [
    "VARIANTS",
    "add_panel",
    "close_all",
    "default_panel",
    "delete_panel",
    "ensure_default_from_env",
    "get_panel",
    "get_provider_for_panel",
    "invalidate_cache",
    "list_inbounds_of",
    "list_panels",
    "register_inbound",
    "settings_for_panel",
    "sync_inbound_meta",
    "test_panel",
    "unregister_inbound",
    "update_panel",
]