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
    BTN_CONFIRM_SPLIT,
    BTN_ENTER_PROMO,
    BTN_REJECT,
    BTN_REMOVE_PROMO,
    BTN_SEND_RECEIPT,
    BTN_SIZE_10GB,
    BTN_SIZE_1GB,
    BTN_SIZE_2GB,
    BTN_SIZE_5GB,
    BTN_SIZE_20GB,
    BTN_SPLIT_FOR_OTHER,
    BTN_SPLIT_FOR_SELF,
    BTN_SPLIT_SERVICE,
)
from app.utils.formatting import days_left_text, fa_digits, money, toman_short, traffic


class BuyCB(CallbackData, prefix="buy"):
    """جریان خرید و تمدید."""

    action: str  # durations | packages | checkout | pay | cancel | promo | remove_promo
    duration_id: int = 0
    package_id: int = 0
    service_id: int = 0   # غیرصفر یعنی تمدید
    offer_id: int = 0     # غیرصفر یعنی کد تخفیف اعمال شده


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


class WalletCB(CallbackData, prefix="wlt"):
    """جریان تقسیم سرویس."""

    action: str   # select_service | select_size | confirm_self | ask_recipient | execute | cancel
    service_id: int = 0      # سرویس والد انتخاب‌شده
    allocated_mb: int = 0    # حجم جدا‌شده (مگابایت)
    recipient_id: int = 0    # آیدی تلگرام گیرنده (یا 0 = خودم)


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
    duration_id: int,
    package_id: int,
    service_id: int = 0,
    offer_id: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BTN_CONFIRM_BUY,
        callback_data=BuyCB(
            action="pay",
            duration_id=duration_id,
            package_id=package_id,
            service_id=service_id,
            offer_id=offer_id,
        ),
        style="success",
    )
    # دکمه کد تخفیف یا حذف تخفیف
    if offer_id:
        builder.button(
            text=BTN_REMOVE_PROMO,
            callback_data=BuyCB(
                action="remove_promo",
                duration_id=duration_id,
                package_id=package_id,
                service_id=service_id,
            ),
            style="danger",
        )
    else:
        builder.button(
            text=BTN_ENTER_PROMO,
            callback_data=BuyCB(
                action="promo",
                duration_id=duration_id,
                package_id=package_id,
                service_id=service_id,
            ),
            style="primary",
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
        text=BTN_SPLIT_SERVICE,
        callback_data=WalletCB(action="start_split", service_id=service.id),
        style="success",
    )
    builder.button(
        text=BTN_BACK, callback_data=ServiceCB(action="list", service_id=0),
        style="primary",
    )
    builder.adjust(*cfg_rows, *extra_rows, 1, 1, 1, 1)
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


def package_summary(
    package: Package,
    duration: Duration,
    discount_amount: int = 0,
    bonus_traffic_mb: int = 0,
    offer_title: str = "",
) -> str:
    """خلاصه سفارش برای صفحه تأیید، با نمایش تخفیف در صورت وجود."""
    lines = [
        "🧾 <b>خلاصه سفارش</b>",
        "",
        f"📦 پکیج: <b>{package.title}</b>",
        f"⏱ مدت: <b>{duration.title}</b>",
    ]

    # حجم — با احتساب بونوس
    total_traffic_mb = package.traffic_mb + bonus_traffic_mb
    traffic_str = traffic(total_traffic_mb)
    if bonus_traffic_mb > 0:
        lines.append(
            f"📊 حجم: <b>{traffic_str}</b>  "
            f"<i>(+{traffic(bonus_traffic_mb)} هدیه 🎁)</i>"
        )
    else:
        lines.append(f"📊 حجم: <b>{traffic_str}</b>")

    lines.append(
        f"📱 تعداد دستگاه: <b>{fa_digits(package.device_limit) if package.device_limit else 'نامحدود'}</b>"
    )

    if package.description:
        lines.append(f"\n{package.description}")

    lines.append("")

    # قیمت — با احتساب تخفیف
    if discount_amount > 0:
        final_price = max(0, package.price - discount_amount)
        lines.append(f"💸 قیمت اصلی: <s>{money(package.price)} تومان</s>")
        lines.append(f"🏷 تخفیف ({offer_title}): <b>−{money(discount_amount)} تومان</b>")
        lines.append(f"💰 مبلغ قابل پرداخت: <b>{money(final_price)} تومان</b>")
    else:
        lines.append(f"💰 مبلغ قابل پرداخت: <b>{money(package.price)} تومان</b>")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
#  کیف داده — Split & Transfer (ساده‌شده)
# ══════════════════════════════════════════════════════════════════

def wallet_services_kb(services: list) -> InlineKeyboardMarkup:
    """لیست سرویس‌های قابل تقسیم."""
    from app.services.wallet_service import available_mb

    builder = InlineKeyboardBuilder()
    for svc in services:
        avail = available_mb(svc)
        builder.button(
            text=f"🔹 {svc.title}  ({traffic(avail)} آزاد)",
            callback_data=WalletCB(action="select_service", service_id=svc.id),
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text=BTN_CANCEL,
            callback_data=WalletCB(action="cancel").pack(),
        )
    )
    return builder.as_markup()


def wallet_size_kb(service_id: int, available_mb_val: int) -> InlineKeyboardMarkup:
    """دکمه‌های اندازه استاندارد (پیش‌فرض‌شده).
    
    تنها اندازه‌هایی که ≤ available_mb نمایش داده می‌شوند.
    """
    from app.services.wallet_service import STANDARD_SIZES

    builder = InlineKeyboardBuilder()
    shown = 0
    
    for label, mb in [
        (BTN_SIZE_1GB, STANDARD_SIZES["1gb"]),
        (BTN_SIZE_2GB, STANDARD_SIZES["2gb"]),
        (BTN_SIZE_5GB, STANDARD_SIZES["5gb"]),
        (BTN_SIZE_10GB, STANDARD_SIZES["10gb"]),
        (BTN_SIZE_20GB, STANDARD_SIZES["20gb"]),
    ]:
        if mb <= available_mb_val:
            builder.button(
                text=label,
                callback_data=WalletCB(
                    action="select_size",
                    service_id=service_id,
                    allocated_mb=mb,
                ),
            )
            shown += 1

    # چیدمان: ۲ ستون
    cols = [2] * (shown // 2) + ([1] if shown % 2 else [])
    if cols:
        builder.adjust(*cols)
    
    builder.row(
        InlineKeyboardButton(
            text=BTN_BACK,
            callback_data=WalletCB(action="select_service", service_id=0).pack(),
        )
    )
    return builder.as_markup()


def wallet_recipient_kb(service_id: int, allocated_mb: int) -> InlineKeyboardMarkup:
    """انتخاب: برای خودم یا دیگری."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BTN_SPLIT_FOR_SELF,
        callback_data=WalletCB(
            action="confirm_self",
            service_id=service_id,
            allocated_mb=allocated_mb,
        ),
    )
    builder.button(
        text=BTN_SPLIT_FOR_OTHER,
        callback_data=WalletCB(
            action="ask_recipient",
            service_id=service_id,
            allocated_mb=allocated_mb,
        ),
    )
    builder.button(
        text=BTN_BACK,
        callback_data=WalletCB(action="select_service", service_id=0),
    )
    builder.adjust(1)
    return builder.as_markup()


def wallet_confirm_kb(
    service_id: int,
    allocated_mb: int,
    recipient_username: str | None = None,
    recipient_id: int = 0,
) -> InlineKeyboardMarkup:
    """تأیید نهایی."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=BTN_CONFIRM_SPLIT,
        callback_data=WalletCB(
            action="execute",
            service_id=service_id,
            allocated_mb=allocated_mb,
            recipient_id=recipient_id,
        ),
    )
    builder.button(
        text=BTN_CANCEL,
        callback_data=WalletCB(action="cancel"),
    )
    builder.adjust(1)
    return builder.as_markup()
