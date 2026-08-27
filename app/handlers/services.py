from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Service, ServiceStatus, User
from app.keyboards import inline
from app.services import provisioning
from app.texts import BTN_MY_SERVICES, MSG_NO_SERVICES
from app.utils.formatting import (
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


def _detail_text(service: Service) -> str:
    total = service.traffic_mb * (1024 ** 2)
    lines = [
        f"🔎 <b>{service.title}</b>",
        "",
        f"وضعیت: {_STATUS_LABEL.get(service.status, '—')}",
        f"⏳ انقضا: <b>{jalali_date(service.expires_at)}</b> "
        f"({days_left_text(service.expires_at)})",
        f"📊 حجم کل: <b>{traffic(service.traffic_mb)}</b>",
        f"📈 مصرف: {usage_text(service.used_bytes, total)}",
    ]
    if service.sub_link:
        lines.append(f"\n🔗 لینک اشتراک:\n<code>{service.sub_link}</code>")
    lines.append(f"\n🔐 کانفیگ:\n<code>{service.config_link}</code>")
    return "\n".join(lines)


@router.message(F.text == BTN_MY_SERVICES)
async def my_services(message: Message, session: AsyncSession, user: User) -> None:
    services = await _user_services(session, user.id)
    if not services:
        await message.answer(MSG_NO_SERVICES)
        return

    active = sum(1 for s in services if s.status is ServiceStatus.ACTIVE)
    header = (
        f"📋 <b>سرویس‌های شما</b>\n"
        f"تعداد کل: {fa_digits(len(services))} | فعال: {fa_digits(active)}\n\n"
        "برای مشاهده جزئیات هر سرویس روی آن بزنید:"
    )
    await message.answer(header, reply_markup=inline.services_kb(services))


@router.callback_query(inline.ServiceCB.filter(F.action == "list"))
async def back_to_list(
    call: CallbackQuery, session: AsyncSession, user: User
) -> None:
    services = await _user_services(session, user.id)
    if not services:
        await call.message.edit_text(MSG_NO_SERVICES)
        await call.answer()
        return
    await call.message.edit_text(
        "📋 <b>سرویس‌های شما</b>\nبرای جزئیات روی هر سرویس بزنید:",
        reply_markup=inline.services_kb(services),
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
    await call.message.edit_text(
        _detail_text(service),
        reply_markup=inline.service_detail_kb(service),
        disable_web_page_preview=True,
    )
    await call.answer()


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
    service = await provisioning.sync_usage(session, service)
    try:
        await call.message.edit_text(
            _detail_text(service),
            reply_markup=inline.service_detail_kb(service),
            disable_web_page_preview=True,
        )
    except Exception:  # noqa: BLE001 — پیام تغییری نکرده
        pass
