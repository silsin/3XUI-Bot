from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Duration, Package, Service
from app.texts import (
    BTN_APPROVE,
    BTN_BACK,
    BTN_CANCEL,
    BTN_CONFIRM_BUY,
    BTN_REJECT,
    BTN_SEND_RECEIPT,
)
from app.utils.formatting import days_left_text, fa_digits, money, toman_short, traffic


class BuyCB(CallbackData, prefix="buy"):
    """جریان خرید و تمدید."""

    action: str  # durations | packages | checkout | pay | cancel
    duration_id: int = 0
    package_id: int = 0
    service_id: int = 0  # غیرصفر یعنی تمدید


class ServiceCB(CallbackData, prefix="srv"):
    action: str  # view | refresh | list | renew | cfg
    service_id: int = 0
    client_id: int = 0  # برای action=cfg


class ReceiptCB(CallbackData, prefix="rcp"):
    action: str  # approve | reject
    order_id: int


class PointsCB(CallbackData, prefix="pts"):
    action: str  # redeem | confirm
    days: int = 0


def durations_kb(
    durations: list[Duration], service_id: int = 0
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in durations:
        builder.button(
            text=item.title,
            callback_data=BuyCB(
                action="packages", duration_id=item.id, service_id=service_id
            ),
            style="primary",
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(
            text=BTN_CANCEL,
            callback_data=BuyCB(action="cancel", service_id=service_id).pack(),
            style="danger",
        )
    )
    return builder.as_markup()


def packages_kb(
    packages: list[Package], duration_id: int, service_id: int = 0
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in packages:
        label = f"{item.title} — {money(item.price)} تومان"
        builder.button(
            text=label,
            callback_data=BuyCB(
                action="checkout",
                duration_id=duration_id,
                package_id=item.id,
                service_id=service_id,
            ),
            style="success",
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text=BTN_BACK,
            callback_data=BuyCB(action="durations", service_id=service_id).pack(),
            style="primary",
        )
    )
    return builder.as_markup()


def checkout_kb(
    duration_id: int, package_id: int, service_id: int = 0
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BTN_CONFIRM_BUY,
        callback_data=BuyCB(
            action="pay",
            duration_id=duration_id,
            package_id=package_id,
            service_id=service_id,
        ),
        style="success",
    )
    builder.button(
        text=BTN_BACK,
        callback_data=BuyCB(
            action="packages", duration_id=duration_id, service_id=service_id
        ),
        style="primary",
    )
    builder.adjust(1)
    return builder.as_markup()


def payment_kb(
    order_id: int, card_number: str = "", amount: int = 0
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows: list[int] = []

    # دکمه‌های «کپی» بومی تلگرام (tap-to-copy)
    card_digits = "".join(ch for ch in card_number if ch.isdigit())
    copy_row = 0
    if card_digits:
        builder.button(
            text="کپی شماره کارت",
            copy_text=CopyTextButton(text=card_digits),
            style="primary",
        )
        copy_row += 1
    if amount:
        builder.button(
            text=toman_short(amount),
            copy_text=CopyTextButton(text=str(int(amount))),
            style="primary",
        )
        copy_row += 1
    if copy_row:
        rows.append(copy_row)

    builder.button(
        text=BTN_SEND_RECEIPT,
        callback_data=f"receipt:start:{order_id}",
        style="success",
    )
    builder.button(
        text=BTN_CANCEL,
        callback_data=f"receipt:cancel:{order_id}",
        style="danger",
    )
    rows += [1, 1]
    builder.adjust(*rows)
    return builder.as_markup()


def services_kb(services: list[Service]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in services:
        mark = "🎁" if item.is_trial else "🔹"
        builder.button(
            text=f"{mark} {item.title} ({days_left_text(item.expires_at)})",
            callback_data=ServiceCB(action="view", service_id=item.id),
            style="primary",
        )
    builder.adjust(1)
    return builder.as_markup()


def service_detail_kb(service: Service) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # یک دکمه برای هر کانفیگ (پروتکل)
    clients = sorted(getattr(service, "clients", []), key=lambda c: c.id)
    cfg_rows: list[int] = []
    if clients:
        for c in clients:
            label = c.label or (c.protocol or "config").upper()
            builder.button(
                text=f"📥 {label}",
                callback_data=ServiceCB(
                    action="cfg", service_id=service.id, client_id=c.id
                ),
                style="primary",
            )
        # دو ستونه
        full = len(clients) // 2
        cfg_rows = [2] * full + ([1] if len(clients) % 2 else [])

    from app.config import get_settings

    extra_rows: list[int] = []
    if get_settings().sub_public_url and getattr(service, "sub_id", ""):
        builder.button(
            text="🔗 لینک اشتراک + QR",
            callback_data=ServiceCB(action="sub", service_id=service.id),
            style="primary",
        )
        extra_rows.append(1)

    builder.button(
        text="🔄 به‌روزرسانی مصرف",
        callback_data=ServiceCB(action="refresh", service_id=service.id),
        style="primary",
    )
    builder.button(
        text="♻️ تمدید این سرویس",
        callback_data=BuyCB(action="durations", service_id=service.id),
        style="success",
    )
    builder.button(
        text=BTN_BACK, callback_data=ServiceCB(action="list", service_id=0),
        style="primary",
    )
    builder.adjust(*cfg_rows, *extra_rows, 1, 1, 1)
    return builder.as_markup()


def receipt_review_kb(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BTN_APPROVE,
        callback_data=ReceiptCB(action="approve", order_id=order_id),
        style="success",
    )
    builder.button(
        text=BTN_REJECT,
        callback_data=ReceiptCB(action="reject", order_id=order_id),
        style="danger",
    )
    builder.adjust(2)
    return builder.as_markup()


def points_kb(available_days: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if available_days > 0:
        builder.button(
            text=f"🎁 دریافت {fa_digits(available_days)} روز اشتراک هدیه",
            callback_data=PointsCB(action="redeem", days=available_days),
            style="success",
        )
    builder.adjust(1)
    return builder.as_markup()


def invite_kb(link: str, share_text: str) -> InlineKeyboardMarkup:
    from urllib.parse import quote

    builder = InlineKeyboardBuilder()
    builder.button(
        text="📤 ارسال به دوستان",
        url=f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}",
        style="primary",
    )
    return builder.as_markup()


def package_summary(package: Package, duration: Duration) -> str:
    """خلاصه سفارش برای صفحه تأیید."""
    lines = [
        "🧾 <b>خلاصه سفارش</b>",
        "",
        f"📦 پکیج: <b>{package.title}</b>",
        f"⏱ مدت: <b>{duration.title}</b>",
        f"📊 حجم: <b>{traffic(package.traffic_mb)}</b>",
        f"📱 تعداد دستگاه: <b>{fa_digits(package.device_limit) if package.device_limit else 'نامحدود'}</b>",
    ]
    if package.description:
        lines.append(f"\n{package.description}")
    lines += ["", f"💰 مبلغ قابل پرداخت: <b>{money(package.price)} تومان</b>"]
    return "\n".join(lines)
