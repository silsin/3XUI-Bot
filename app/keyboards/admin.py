from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Duration, Offer, Package
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
    b.button(text="🛰 پنل‌ها و اینباندها", callback_data=AdminCB(action="panels"))
    b.button(text="🏷 تخفیف‌ها و پیشنهادها", callback_data=AdminCB(action="offers"))
    b.button(text="🔐 تنظیمات کانال الزامی", callback_data="setting:required_channel")
    b.button(text="💰 مدیریت کیف پول", callback_data="wallet_menu:home")
    b.button(text="👥 کاربران", callback_data=AdminCB(action="users"))
    b.button(text="📊 آمار", callback_data=AdminCB(action="stats"))
    b.button(text="📈 گزارش فعالیت کاربران", callback_data=AdminCB(action="activity"))
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

def activity_home_kb() -> InlineKeyboardMarkup:
    """صفحه اصلی گزارش فعالیت."""
    b = InlineKeyboardBuilder()
    b.button(text="📋 آخرین فعالیت‌ها", callback_data=AdminCB(action="activity_recent"))
    b.button(text="🔍 جستجوی کاربر", callback_data=AdminCB(action="activity_search"))
    b.adjust(1)
    b.row(_back("home"))
    return b.as_markup()


def back_activity() -> InlineKeyboardMarkup:
    """دکمه بازگشت به صفحه فعالیت."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=BTN_BACK, callback_data=AdminCB(action="activity").pack()))
    return b.as_markup()


# ─────────────────────── کیبوردهای تخفیف ────────────────────────────

def offers_list_kb(offer_list: list) -> InlineKeyboardMarkup:
    """لیست تخفیف‌ها با دکمه مشاهده هر کدام."""
    b = InlineKeyboardBuilder()
    for o in offer_list:
        st = "🟢" if o.is_active else "⚪️"
        b.button(
            text=f"{st} #{o.id} {o.title}",
            callback_data=AdminCB(action="offer_view", arg=o.id),
        )
    b.adjust(1)
    b.row(InlineKeyboardButton(text="➕ تخفیف جدید", callback_data=AdminCB(action="offer_add").pack()))
    b.row(_back("home"))
    return b.as_markup()


def offer_detail_kb(offer) -> InlineKeyboardMarkup:
    """دکمه‌های مدیریت یک تخفیف."""
    b = InlineKeyboardBuilder()
    toggle_label = "⚪️ غیرفعال‌سازی" if offer.is_active else "🟢 فعال‌سازی"
    b.button(
        text=toggle_label,
        callback_data=AdminCB(action="offer_toggle", arg=offer.id),
    )
    b.button(
        text="🗑 حذف تخفیف",
        callback_data=AdminCB(action="offer_del_confirm", arg=offer.id),
    )
    b.adjust(2)
    b.row(_back("offers"))

# ---------- پنل‌ها و اینباندها ----------


def panels_list(panels: list) -> InlineKeyboardMarkup:
    """فهرست پنل‌ها."""
    b = InlineKeyboardBuilder()
    for p in panels:
        state = "🟢" if p.is_active else "⚪️"
        b.button(
            text=f"{state} {p.title}",
            callback_data=AdminCB(action="panel_view", arg=p.id),
        )
    if panels:
        b.adjust(1)
    b.button(text="➕ افزودن پنل", callback_data=AdminCB(action="panel_new"))
    b.button(text="🔄 از .env", callback_data=AdminCB(action="panel_seed"))
    b.row(_back("home"))
    return b.as_markup()


def panel_view(panel_id: int) -> InlineKeyboardMarkup:
    """مدیریت یک پنل."""
    b = InlineKeyboardBuilder()
    b.button(
        text="🛰 اینباندهای این پنل",
        callback_data=AdminCB(action="inb_list", arg=panel_id),
    )
    b.button(
        text="🛠 ساخت اینباند",
        callback_data=AdminCB(action="inb_add", arg=panel_id),
    )
    b.button(
        text="🔌 تست اتصال",
        callback_data=AdminCB(action="panel_test", arg=panel_id),
    )
    b.button(
        text="✏️ ویرایش مشخصات",
        callback_data=AdminCB(action="panel_edit_menu", arg=panel_id),
    )
    b.button(
        text="🔁 تازه‌سازی کش",
        callback_data=AdminCB(action="panel_refresh", arg=panel_id),
    )
    b.button(
        text="⚪️/🟢 فعال‌سازی",
        callback_data=AdminCB(action="panel_toggle", arg=panel_id),
    )
    b.button(
        text="🗑 حذف پنل",
        callback_data=AdminCB(action="panel_del_confirm", arg=panel_id),
    )
    b.adjust(2)
    b.row(_back("panels"))
    return b.as_markup()


def panel_edit_fields(panel_id: int) -> InlineKeyboardMarkup:
    """فیلدهای قابل ویرایش پنل."""
    fields = [
        ("title", "🏷 عنوان"),
        ("base_url", "🌐 آدرس"),
        ("web_base_path", "🧭 مسیر پایه"),
        ("api_token", "🔑 توکن"),
        ("username", "👤 نام کاربری"),
        ("password", "🔒 گذرواژه"),
        ("node_host", "📍 هاست لینک"),
        ("sub_base_url", "🔗 آدرس اشتراک"),
        ("variant", "🧬 نوع پنل"),
    ]
    b = InlineKeyboardBuilder()
    for key, label in fields:
        b.button(
            text=label,
            callback_data=AdminCB(action="panel_edit_field", arg=panel_id, field=key),
        )
    b.adjust(2)
    b.row(_back("panel_view", panel_id))
    return b.as_markup()


def variant_choose() -> InlineKeyboardMarkup:
    """انتخاب نوع پنل هنگام ساخت."""
    from app.services.panel_service import VARIANTS

    b = InlineKeyboardBuilder()
    for value, label in VARIANTS.items():
        b.button(
            text=label,
            callback_data=AdminCB(action="panel_new_variant", field=value),
        )
    b.adjust(1)
    b.row(_back("panels"))
    return b.as_markup()


def inbounds_list(panel_id: int, rows: list) -> InlineKeyboardMarkup:
    """فهرست اینباندهای ثبت‌شده یک پنل."""
    b = InlineKeyboardBuilder()
    for r in rows:
        state = "🟢" if r.is_active else "⚪️"
        label = r.remark or f"#{r.inbound_id}"
        b.button(
            text=f"{state} {label} ({r.protocol} :{r.port})",
            callback_data=AdminCB(action="inb_view", arg=r.id),
        )
    if rows:
        b.adjust(1)
    b.button(
        text="➕ از پنل بخوان",
        callback_data=AdminCB(action="inb_fetch", arg=panel_id),
    )
    b.button(
        text="🛠 ساخت اینباند",
        callback_data=AdminCB(action="inb_add", arg=panel_id),
    )
    b.row(_back("panel_view", panel_id))
    return b.as_markup()


def inbound_view(row_id: int, panel_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text="🔁 تازه‌سازی اطلاعات",
        callback_data=AdminCB(action="inb_sync", arg=row_id),
    )
    b.button(
        text="🔀 تغییر وضعیت",
        callback_data=AdminCB(action="inb_toggle", arg=row_id),
    )
    b.button(
        text="🗑 فقط از ربات",
        callback_data=AdminCB(action="inb_unreg_confirm", arg=row_id),
    )
    b.button(
        text="🗑 از پنل هم حذف کن",
        callback_data=AdminCB(action="inb_del_confirm", arg=row_id),
    )
    b.adjust(2)
    b.row(_back("inb_list", panel_id))
    return b.as_markup()


def confirm(text: str, yes_action: str, arg: int, back_action: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text="بله، حذف شود",
        callback_data=AdminCB(action=yes_action, arg=arg).pack(),
    )
    b.button(
        text="انصراف",
        callback_data=AdminCB(action=back_action, arg=arg).pack(),
    )
    b.adjust(2)
    return b.as_markup()


def inbound_protocol_choose(panel_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for proto in ("vless", "vmess", "trojan", "shadowsocks"):
        b.button(
            text=proto,
            callback_data=AdminCB(
                action="inb_proto", arg=panel_id, field=proto
            ),
        )
    b.adjust(2)
    b.row(_back("inb_list", panel_id))
    return b.as_markup()


def inbound_network_choose(panel_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for net in ("tcp", "ws", "grpc", "xhttp"):
        b.button(
            text=net,
            callback_data=AdminCB(action="inb_net", arg=panel_id, field=net),
        )
    b.adjust(2)
    b.row(_back("inb_list", panel_id))
    return b.as_markup()


def inbound_security_choose(panel_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for sec in ("none", "tls", "reality"):
        b.button(
            text=sec,
            callback_data=AdminCB(action="inb_sec", arg=panel_id, field=sec),
        )
    b.adjust(3)
    b.row(_back("inb_list", panel_id))
    return b.as_markup()

    return b.as_markup()