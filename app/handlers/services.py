from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import Service, ServiceClient, ServiceStatus, User
from app.keyboards import inline
from app.services import activity_service as activity
from app.services import provisioning
from app.services import wallet_service as wallet
from app.texts import BTN_MY_SERVICES, MSG_NO_SERVICES, MSG_WALLET_NO_SERVICE, MSG_WALLET_SELECT_TYPE
from app.utils.formatting import (
    days_left,
    days_left_text,
    fa_digits,
    jalali_date,
    traffic,
    usage_text,
)
from app.utils.qr import make_qr_png


def sub_link_for(service: Service) -> str:
    """لینک اشتراک ربات برای این سرویس (همه پروتکل‌ها)."""
    base = get_settings().sub_public_url
    if base and service.sub_id:
        return f"{base.rstrip('/')}/sub/{service.sub_id}"
    return service.sub_link or ""

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
    sub = sub_link_for(service)
    if sub:
        lines.append(
            f"\n🔗 <b>لینک اشتراک (همه پروتکل‌ها):</b>\n<code>{sub}</code>"
        )

    clients = sorted(service.clients, key=lambda c: c.id)
    if clients:
        lines.append(
            "\n🔐 برای دریافت کانفیگ یا QR هر پروتکل روی دکمه‌ی آن بزنید. "
            "اگر یکی وصل نشد، دیگری را امتحان کنید."
        )
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
    # لاگ فعالیت
    await activity.log_activity(session, user.id, activity.Actions.VIEW_SERVICES)


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
    # لاگ فعالیت
    await activity.log_activity(
        session, user.id, activity.Actions.VIEW_CONFIG,
        {"service_id": service.id, "title": service.title}
    )


@router.callback_query(inline.ServiceCB.filter(F.action == "cfg"))
async def send_single_config(
    call: CallbackQuery,
    callback_data: inline.ServiceCB,
    session: AsyncSession,
    user: User,
) -> None:
    client = await session.get(ServiceClient, callback_data.client_id)
    if client is None:
        await call.answer("کانفیگ یافت نشد.", show_alert=True)
        return
    service = await session.get(Service, client.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("کانفیگ یافت نشد.", show_alert=True)
        return

    label = client.label or (client.protocol or "config").upper()
    link = client.config_link
    if not link:
        await call.answer("کانفیگ خالی است.", show_alert=True)
        return
    await call.answer()
    from app.handlers.delivery import send_config_message

    await send_config_message(call.bot, call.message.chat.id, label, link)
    # لاگ فعالیت
    await activity.log_activity(
        session, user.id, activity.Actions.COPY_LINK,
        {"service_id": service.id, "protocol": client.protocol, "label": label}
    )


@router.callback_query(inline.ServiceCB.filter(F.action == "sub"))
async def send_sub_link(
    call: CallbackQuery,
    callback_data: inline.ServiceCB,
    session: AsyncSession,
    user: User,
) -> None:
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return
    sub = sub_link_for(service)
    if not sub:
        await call.answer("لینک اشتراک فعال نیست.", show_alert=True)
        return
    await call.answer()
    qr = BufferedInputFile(make_qr_png(sub), filename="subscription.png")
    await call.message.answer_photo(
        qr,
        caption=(
            "🔗 <b>لینک اشتراک (همه پروتکل‌ها)</b>\n"
            "QR را اسکن کنید یا لینک زیر را به‌عنوان Subscription اضافه کنید 👇"
        ),
    )
    await call.message.answer(f"<code>{sub}</code>", disable_web_page_preview=True)


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


@router.callback_query(inline.ServiceCB.filter(F.action == "wallet"))
async def open_wallet(
    call: CallbackQuery,
    callback_data: inline.ServiceCB,
    session: AsyncSession,
    user: User,
) -> None:
    """ورود به کیف داده از صفحه جزئیات سرویس."""
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    if not wallet._is_active_splittable(service):
        await call.answer(MSG_WALLET_NO_SERVICE, show_alert=True)
        return

    avail = wallet.available_mb(service)
    from app.utils.formatting import jalali_date
    text = MSG_WALLET_SELECT_TYPE.format(
        title=service.title,
        available=traffic(avail),
        expires=jalali_date(service.expires_at),
    )
    await call.message.edit_text(
        text,
        reply_markup=inline.wallet_type_kb(service.id),
    )
    await call.answer()
    await activity.log_activity(session, user.id, "wallet_entry", {"service_id": service.id})
