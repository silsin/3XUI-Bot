from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Service, ServiceStatus, User
from app.keyboards import inline
from app.services import provisioning
from app.texts import BTN_MY_SERVICES, MSG_NO_SERVICES
from app.utils.formatting import (
    days_left,
    days_left_text,
    fa_digits,
    jalali_date,
    traffic,
    usage_text,
)

logger = logging.getLogger(__name__)
router = Router(name="services")

_STATUS_LABEL = {
    ServiceStatus.ACTIVE: "🟢 فعال",
    ServiceStatus.EXPIRED: "🔴 منقضی",
    ServiceStatus.DISABLED: "⛔️ غیرفعال",
}


def _is_expired(service: Service) -> bool:
    """انقضا را بلادرنگ از روی تاریخ می‌سنجد (مستقل از همگام‌سازی زمان‌بند)."""
    if service.status is ServiceStatus.EXPIRED:
        return True
    if service.expires_at is None:  # نامحدود
        return False
    return days_left(service.expires_at) == 0


def _effective_status(service: Service) -> ServiceStatus:
    return ServiceStatus.EXPIRED if _is_expired(service) else service.status


async def _user_services(session: AsyncSession, user_id: int) -> list[Service]:
    return list(
        (
            await session.execute(
                select(Service)
                .where(Service.user_id == user_id)
                .order_by(Service.created_at.desc())
            )
        ).scalars().all()
    )


async def _get_service(session: AsyncSession, service_id: int) -> Service | None:
    return (
        await session.execute(
            select(Service)
            .where(Service.id == service_id)
            .options(selectinload(Service.clients))
        )
    ).scalar_one_or_none()


def _detail_text(service: Service) -> str:
    total = service.traffic_mb * (1024 ** 2)
    lines = [
        f"🔎 <b>{service.title}</b>",
        "",
        f"وضعیت: {_STATUS_LABEL.get(_effective_status(service), '—')}",
        f"⏳ انقضا: <b>{jalali_date(service.expires_at)}</b> "
        f"({days_left_text(service.expires_at)})",
        f"📊 حجم کل: <b>{traffic(service.traffic_mb)}</b>",
        f"📈 مصرف: {usage_text(service.used_bytes, total)}",
    ]
    if service.sub_link:
        lines.append(f"\n🔗 لینک اشتراک:\n<code>{service.sub_link}</code>")

    clients = sorted(service.clients, key=lambda c: c.id)
    if clients:
        lines.append(
            "\n🔐 <b>کانفیگ‌ها</b> — اگر یکی وصل نشد، دیگری را امتحان کنید:"
        )
        for c in clients:
            label = c.label or (c.protocol or "config").upper()
            lines.append(f"\n▫️ <b>{label}</b>\n<code>{c.config_link}</code>")
    elif service.config_link:
        lines.append(f"\n🔐 کانفیگ:\n<code>{service.config_link}</code>")
    return "\n".join(lines)


def _split_active(services: list[Service]) -> tuple[list[Service], int]:
    active = [s for s in services if not _is_expired(s)]
    return active, len(services) - len(active)


@router.message(F.text == BTN_MY_SERVICES)
async def my_services(message: Message, session: AsyncSession, user: User) -> None:
    services = await _user_services(session, user.id)
    if not services:
        await message.answer(MSG_NO_SERVICES)
        return

    active, expired = _split_active(services)
    if not active:
        await message.answer(
            "🔴 همه سرویس‌های شما منقضی شده‌اند.\n"
            "برای تمدید از «♻️ تمدید سرویس» استفاده کنید."
        )
        return

    header = f"📋 <b>سرویس‌های فعال شما</b>\nتعداد: {fa_digits(len(active))}"
    if expired:
        header += f" | منقضی: {fa_digits(expired)} (از «♻️ تمدید سرویس» تمدید کنید)"
    header += "\n\nبرای مشاهده جزئیات هر سرویس روی آن بزنید:"
    await message.answer(header, reply_markup=inline.services_kb(active))


@router.callback_query(inline.ServiceCB.filter(F.action == "list"))
async def back_to_list(
    call: CallbackQuery, session: AsyncSession, user: User
) -> None:
    services = await _user_services(session, user.id)
    active, _ = _split_active(services)
    if not active:
        await call.message.edit_text(
            "🔴 سرویس فعالی ندارید. برای تمدید از «♻️ تمدید سرویس» استفاده کنید."
        )
        await call.answer()
        return
    await call.message.edit_text(
        "📋 <b>سرویس‌های فعال شما</b>\nبرای جزئیات روی هر سرویس بزنید:",
        reply_markup=inline.services_kb(active),
    )
    await call.answer()


@router.callback_query(inline.ServiceCB.filter(F.action == "view"))
async def view_service(
    call: CallbackQuery,
    callback_data: inline.ServiceCB,
    session: AsyncSession,
    user: User,
) -> None:
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return
    # اعمال سهمیه/انقضا در لحظه مشاهده
    service = await provisioning.sync_service(session, service)
    await call.answer()
    try:
        await call.message.edit_text(
            _detail_text(service),
            reply_markup=inline.service_detail_kb(service),
            disable_web_page_preview=True,
        )
    except Exception:  # noqa: BLE001 — پیام تغییری نکرده
        pass


@router.callback_query(inline.ServiceCB.filter(F.action == "refresh"))
async def refresh_service(
    call: CallbackQuery,
    callback_data: inline.ServiceCB,
    session: AsyncSession,
    user: User,
) -> None:
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return
    await call.answer("در حال به‌روزرسانی...")
    service = await provisioning.sync_service(session, service)
    try:
        await call.message.edit_text(
            _detail_text(service),
            reply_markup=inline.service_detail_kb(service),
            disable_web_page_preview=True,
        )
    except Exception:  # noqa: BLE001 — پیام تغییری نکرده
        pass
