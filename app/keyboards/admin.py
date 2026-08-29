from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Duration, Package
from app.texts import BTN_BACK
from app.utils.formatting import fa_digits, money, traffic


class AdminCB(CallbackData, prefix="adm"):
    action: str
    arg: int = 0
    arg2: int = 0
    # باید Optional باشد؛ رشته خالی هنگام unpack به None تبدیل می‌شود
    field: str | None = None


def home() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📝 متن‌ها و پیام‌ها", callback_data=AdminCB(action="texts"))
    b.button(text="🖼 تصویر خوش‌آمد", callback_data=AdminCB(action="image"))
    b.button(text="💳 اطلاعات پرداخت", callback_data=AdminCB(action="payment"))
    b.button(text="⏱ مدت‌ها و پکیج‌ها", callback_data=AdminCB(action="durations"))
    b.button(text="🎁 تنظیمات تست رایگان", callback_data=AdminCB(action="trial"))
    b.button(text="🏅 تنظیمات امتیاز", callback_data=AdminCB(action="points"))
    b.button(text="🧩 اینباندهای کانفیگ", callback_data=AdminCB(action="multi"))
    b.button(text="👥 کاربران", callback_data=AdminCB(action="users"))
    b.button(text="📊 آمار", callback_data=AdminCB(action="stats"))
    b.button(text="📣 پیام همگانی", callback_data=AdminCB(action="broadcast"))
    b.button(text="🔗 بازتولید لینک‌ها", callback_data=AdminCB(action="regen"))
    b.button(text="🔌 تست اتصال پنل", callback_data=AdminCB(action="ping"))
    b.adjust(2)
    return b.as_markup()


def _back(action: str, arg: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=BTN_BACK, callback_data=AdminCB(action=action, arg=arg).pack()
    )


def back_home() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=BTN_BACK, callback_data=AdminCB(action="home").pack()))
    return b.as_markup()


def edit_list(fields: list[tuple[str, str]], back_action: str = "home") -> InlineKeyboardMarkup:
    """لیست کلیدهای قابل ویرایش: (key, label)."""
    b = InlineKeyboardBuilder()
    for key, label in fields:
        b.button(text=label, callback_data=AdminCB(action="edit", field=key))
    b.adjust(1)
    b.row(_back(back_action))
    return b.as_markup()


def durations_list(durations: list[Duration]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in durations:
        state = "🟢" if d.is_active else "⚪️"
        b.button(
            text=f"{state} {d.title} ({fa_digits(d.days)} روز)",
            callback_data=AdminCB(action="dur_view", arg=d.id),
        )
    b.adjust(1)
    b.row(InlineKeyboardButton(text="➕ افزودن مدت", callback_data=AdminCB(action="dur_add").pack()))
    b.row(_back("home"))
    return b.as_markup()


def duration_view(duration: Duration, packages: list[Package]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in packages:
        state = "🟢" if p.is_active else "⚪️"
        b.button(
            text=f"{state} {p.title} — {money(p.price)}",
            callback_data=AdminCB(action="pkg_view", arg=p.id),
        )
    b.adjust(1)
    b.row(
        InlineKeyboardButton(
            text="➕ افزودن پکیج",
            callback_data=AdminCB(action="pkg_add", arg=duration.id).pack(),
        )
    )
    toggle = "غیرفعال‌سازی" if duration.is_active else "فعال‌سازی"
    b.row(
        InlineKeyboardButton(
            text=f"{'⚪️' if duration.is_active else '🟢'} {toggle} مدت",
            callback_data=AdminCB(action="dur_toggle", arg=duration.id).pack(),
        ),
        InlineKeyboardButton(
            text="🗑 حذف مدت",
            callback_data=AdminCB(action="dur_del", arg=duration.id).pack(),
        ),
    )
    b.row(_back("durations"))
    return b.as_markup()


PKG_FIELDS = [
    ("title", "عنوان"),
    ("traffic_mb", "حجم (مگابایت، ۰=نامحدود)"),
    ("price", "قیمت (تومان)"),
    ("device_limit", "تعداد دستگاه (۰=نامحدود)"),
    ("inbound_id", "شماره inbound پنل"),
    ("description", "توضیحات"),
]


def package_view(package: Package) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for field, label in PKG_FIELDS:
        b.button(
            text=f"✏️ {label}",
            callback_data=AdminCB(action="pkg_edit", arg=package.id, field=field),
        )
    b.adjust(2)
    toggle = "غیرفعال" if package.is_active else "فعال"
    b.row(
        InlineKeyboardButton(
            text=f"{'⚪️' if package.is_active else '🟢'} {toggle}‌سازی",
            callback_data=AdminCB(action="pkg_toggle", arg=package.id).pack(),
        ),
        InlineKeyboardButton(
            text="🗑 حذف پکیج",
            callback_data=AdminCB(action="pkg_del", arg=package.id).pack(),
        ),
    )
    b.row(
        InlineKeyboardButton(
            text=BTN_BACK,
            callback_data=AdminCB(action="dur_view", arg=package.duration_id).pack(),
        )
    )
    return b.as_markup()


def confirm(action: str, arg: int, back_action: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ بله، مطمئنم", callback_data=AdminCB(action=action, arg=arg))
    b.button(text="🔙 خیر", callback_data=AdminCB(action=back_action, arg=arg))
    b.adjust(2)
    return b.as_markup()


def user_actions(user_id: int, is_blocked: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text="🎁 اعطای روز رایگان",
        callback_data=AdminCB(action="user_gift", arg=user_id),
    )
    if is_blocked:
        b.button(text="✅ رفع مسدودی", callback_data=AdminCB(action="user_unblock", arg=user_id))
    else:
        b.button(text="⛔️ مسدودسازی", callback_data=AdminCB(action="user_block", arg=user_id))
    b.adjust(1)
    b.row(_back("users"))
    return b.as_markup()
