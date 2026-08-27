"""پنل مدیریت درون‌ربات: تنظیمات، پکیج‌ها، کاربران، آمار."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Duration,
    Order,
    OrderStatus,
    Package,
    Service,
    ServiceStatus,
    User,
)
from app.filters import IsAdmin
from app.keyboards import admin as kb
from app.keyboards import reply
from app.services import points_service as pts
from app.services import settings_service as cfg
from app.services.vpn import VpnError, get_provider
from app.states import AdminFlow
from app.texts import (
    S_BUY_INSTRUCTION,
    S_CARD_HOLDER,
    S_CARD_NUMBER,
    S_CONFIG_CAPTION,
    S_GUIDE_TEXT,
    S_INVITE_TEXT,
    S_POINTS_PER_DAY,
    S_POINTS_TEXT,
    S_REDEEM_INBOUND,
    S_REFERRAL_POINTS,
    S_SUPPORT_TEXT,
    S_TRIAL_DAYS,
    S_TRIAL_ENABLED,
    S_TRIAL_GB,
    S_TRIAL_INBOUND,
    S_WELCOME_IMAGE,
    S_WELCOME_TEXT,
)
from app.utils.formatting import fa_digits, money

logger = logging.getLogger(__name__)
router = Router(name="admin_panel")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

TEXT_FIELDS = [
    (S_WELCOME_TEXT, "پیام خوش‌آمد ({name})"),
    (S_BUY_INSTRUCTION, "راهنمای پرداخت"),
    (S_CONFIG_CAPTION, "متن تحویل کانفیگ"),
    (S_GUIDE_TEXT, "آموزش استفاده"),
    (S_SUPPORT_TEXT, "پشتیبانی"),
    (S_INVITE_TEXT, "متن دعوت"),
    (S_POINTS_TEXT, "متن امتیاز"),
]
PAYMENT_FIELDS = [(S_CARD_NUMBER, "شماره کارت"), (S_CARD_HOLDER, "نام صاحب کارت")]
TRIAL_NUM_FIELDS = [
    (S_TRIAL_DAYS, "مدت تست (روز)"),
    (S_TRIAL_GB, "حجم تست (گیگ)"),
    (S_TRIAL_INBOUND, "شماره inbound تست"),
]
POINTS_FIELDS = [
    (S_REFERRAL_POINTS, "امتیاز هر دعوت موفق"),
    (S_POINTS_PER_DAY, "امتیاز لازم برای ۱ روز"),
    (S_REDEEM_INBOUND, "شماره inbound اشتراک هدیه"),
]
NUMERIC_KEYS = {
    S_TRIAL_DAYS, S_TRIAL_GB, S_TRIAL_INBOUND,
    S_REFERRAL_POINTS, S_POINTS_PER_DAY, S_REDEEM_INBOUND,
}

HOME_TEXT = "🛠 <b>پنل مدیریت</b>\nیک بخش را انتخاب کنید:"


# ---------- ورود ----------


@router.message(F.text == reply.ADMIN_BUTTON)
async def open_panel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HOME_TEXT, reply_markup=kb.home())


@router.callback_query(kb.AdminCB.filter(F.action == "home"))
async def go_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(HOME_TEXT, reply_markup=kb.home())
    await call.answer()


# ---------- گروه‌های تنظیمات ----------


@router.callback_query(kb.AdminCB.filter(F.action == "texts"))
async def show_texts(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "📝 کدام متن را ویرایش می‌کنید؟",
        reply_markup=kb.edit_list(TEXT_FIELDS),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "payment"))
async def show_payment(call: CallbackQuery, session: AsyncSession) -> None:
    card = await cfg.get(session, S_CARD_NUMBER)
    holder = await cfg.get(session, S_CARD_HOLDER)
    await call.message.edit_text(
        f"💳 <b>اطلاعات پرداخت فعلی</b>\nکارت: <code>{card}</code>\nصاحب: {holder}",
        reply_markup=kb.edit_list(PAYMENT_FIELDS),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "trial"))
async def show_trial(call: CallbackQuery, session: AsyncSession) -> None:
    enabled = await cfg.get_bool(session, S_TRIAL_ENABLED, True)
    days = await cfg.get_int(session, S_TRIAL_DAYS, 1)
    gb = await cfg.get_int(session, S_TRIAL_GB, 1)
    inbound = await cfg.get_int(session, S_TRIAL_INBOUND, 1)
    text = (
        f"🎁 <b>تست رایگان</b>\n"
        f"وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}\n"
        f"مدت: {fa_digits(days)} روز | حجم: {fa_digits(gb)} گیگ | inbound: {fa_digits(inbound)}"
    )
    markup = kb.edit_list(TRIAL_NUM_FIELDS)
    # افزودن دکمه toggle به بالای لیست
    from aiogram.types import InlineKeyboardButton

    rows = markup.inline_keyboard
    rows.insert(
        0,
        [
            InlineKeyboardButton(
                text="🔴 غیرفعال کن" if enabled else "🟢 فعال کن",
                callback_data=kb.AdminCB(action="trial_toggle").pack(),
            )
        ],
    )
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "trial_toggle"))
async def trial_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    enabled = await cfg.get_bool(session, S_TRIAL_ENABLED, True)
    await cfg.set_value(session, S_TRIAL_ENABLED, "0" if enabled else "1")
    await show_trial(call, session)


@router.callback_query(kb.AdminCB.filter(F.action == "points"))
async def show_points(call: CallbackQuery, session: AsyncSession) -> None:
    ref = await cfg.get_int(session, S_REFERRAL_POINTS, 10)
    per_day = await cfg.get_int(session, S_POINTS_PER_DAY, 10)
    text = (
        f"🏅 <b>تنظیمات امتیاز</b>\n"
        f"هر دعوت موفق: {fa_digits(ref)} امتیاز\n"
        f"هر {fa_digits(per_day)} امتیاز = ۱ روز اشتراک"
    )
    await call.message.edit_text(text, reply_markup=kb.edit_list(POINTS_FIELDS))
    await call.answer()


# ---------- ویرایش یک مقدار ----------


@router.callback_query(kb.AdminCB.filter(F.action == "edit"))
async def edit_field(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession, state: FSMContext
) -> None:
    key = callback_data.field
    current = await cfg.get(session, key)
    await state.set_state(AdminFlow.editing_setting)
    await state.update_data(key=key)
    preview = current if len(current) < 600 else current[:600] + "…"
    hint = "\n\nمی‌توانید از {name}، {amount}، {card_number}، {link} و ... استفاده کنید." if key in {
        S_WELCOME_TEXT, S_BUY_INSTRUCTION, S_INVITE_TEXT, S_POINTS_TEXT, S_CONFIG_CAPTION
    } else ""
    number_hint = "\n\n⚠️ فقط عدد وارد کنید." if key in NUMERIC_KEYS else ""
    await call.message.answer(
        f"مقدار فعلی:\n<code>{preview or '—'}</code>\n\n"
        f"مقدار جدید را بفرستید (/cancel برای انصراف).{hint}{number_hint}"
    )
    await call.answer()


@router.message(AdminFlow.editing_setting)
async def save_setting(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    key = data.get("key", "")
    value = message.text or message.caption or ""
    if key in NUMERIC_KEYS:
        if not value.strip().isdigit():
            await message.answer("⚠️ لطفاً فقط عدد بفرستید.")
            return
    await cfg.set_value(session, key, value)
    await state.clear()
    await message.answer("✅ ذخیره شد.", reply_markup=kb.back_home())


# ---------- تصویر خوش‌آمد ----------


@router.callback_query(kb.AdminCB.filter(F.action == "image"))
async def image_prompt(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    current = await cfg.get(session, S_WELCOME_IMAGE)
    await state.set_state(AdminFlow.editing_image)
    status = "تنظیم‌شده ✅" if current else "تنظیم نشده"
    await call.message.answer(
        f"🖼 تصویر فعلی: {status}\n\n"
        "یک <b>عکس</b> بفرستید تا جایگزین شود.\n"
        "برای حذف تصویر کلمه «حذف» را بفرستید. (/cancel برای انصراف)"
    )
    await call.answer()


@router.message(AdminFlow.editing_image, F.photo)
async def image_save(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await cfg.set_value(session, S_WELCOME_IMAGE, message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ تصویر خوش‌آمد ذخیره شد.", reply_markup=kb.back_home())


@router.message(AdminFlow.editing_image, F.text == "حذف")
async def image_delete(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await cfg.set_value(session, S_WELCOME_IMAGE, "")
    await state.clear()
    await message.answer("✅ تصویر حذف شد.", reply_markup=kb.back_home())


@router.message(AdminFlow.editing_image)
async def image_invalid(message: Message) -> None:
    await message.answer("لطفاً یک عکس بفرستید یا «حذف» را ارسال کنید.")


# ---------- مدت‌ها و پکیج‌ها ----------


async def _durations(session: AsyncSession) -> list[Duration]:
    return list(
        (await session.execute(select(Duration).order_by(Duration.sort_order, Duration.days)))
        .scalars().all()
    )


@router.callback_query(kb.AdminCB.filter(F.action == "durations"))
async def durations_home(call: CallbackQuery, session: AsyncSession) -> None:
    await _render_durations(call, session)
    await call.answer()


async def _render_durations(call: CallbackQuery, session: AsyncSession) -> None:
    durations = await _durations(session)
    await call.message.edit_text(
        "⏱ <b>مدت‌های اشتراک</b>\nبرای مدیریت پکیج‌ها روی هر مورد بزنید:",
        reply_markup=kb.durations_list(durations),
    )


@router.callback_query(kb.AdminCB.filter(F.action == "dur_add"))
async def duration_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.duration_days)
    await call.message.answer("تعداد روزهای این مدت را بفرستید (مثلاً 30):")
    await call.answer()


@router.message(AdminFlow.duration_days)
async def duration_add_save(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("⚠️ یک عدد مثبت بفرستید.")
        return
    days = int(text)
    session.add(Duration(days=days, title=f"{days} روزه", sort_order=days))
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ مدت {fa_digits(days)} روزه اضافه شد. حالا پکیج اضافه کنید.",
        reply_markup=kb.back_home(),
    )


@router.callback_query(kb.AdminCB.filter(F.action == "dur_view"))
async def duration_view(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    duration = await session.get(Duration, callback_data.arg)
    if duration is None:
        await call.answer("یافت نشد.", show_alert=True)
        return
    packages = list(
        (
            await session.execute(
                select(Package).where(Package.duration_id == duration.id)
                .order_by(Package.sort_order, Package.price)
            )
        ).scalars().all()
    )
    await call.message.edit_text(
        f"⏱ <b>{duration.title}</b> ({fa_digits(duration.days)} روز)\n"
        f"تعداد پکیج: {fa_digits(len(packages))}",
        reply_markup=kb.duration_view(duration, packages),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "dur_toggle"))
async def duration_toggle(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    duration = await session.get(Duration, callback_data.arg)
    if duration:
        duration.is_active = not duration.is_active
        await session.commit()
    await duration_view(call, callback_data, session)


@router.callback_query(kb.AdminCB.filter(F.action == "dur_del"))
async def duration_del(call: CallbackQuery, callback_data: kb.AdminCB) -> None:
    await call.message.edit_text(
        "🗑 حذف این مدت و همه پکیج‌های آن؟",
        reply_markup=kb.confirm("dur_del_yes", callback_data.arg, "dur_view"),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "dur_del_yes"))
async def duration_del_yes(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    duration = await session.get(Duration, callback_data.arg)
    if duration:
        await session.delete(duration)
        await session.commit()
    await call.answer("حذف شد.")
    await _render_durations(call, session)


@router.callback_query(kb.AdminCB.filter(F.action == "pkg_add"))
async def package_add(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    duration = await session.get(Duration, callback_data.arg)
    if duration is None:
        await call.answer("مدت یافت نشد.", show_alert=True)
        return
    package = Package(
        duration_id=duration.id,
        title="پکیج جدید",
        traffic_gb=0,
        price=0,
        device_limit=1,
        inbound_id=1,
        is_active=False,
    )
    session.add(package)
    await session.commit()
    await session.refresh(package)
    await call.answer("پکیج ساخته شد؛ مقادیر را ویرایش کنید.")
    await _render_package(call, session, package)


async def _render_package(call: CallbackQuery, session: AsyncSession, package: Package) -> None:
    text = (
        f"📦 <b>{package.title}</b>\n"
        f"حجم: {fa_digits(package.traffic_gb)} گیگ (۰=نامحدود)\n"
        f"قیمت: {money(package.price)} تومان\n"
        f"دستگاه: {fa_digits(package.device_limit)}\n"
        f"inbound: {fa_digits(package.inbound_id)}\n"
        f"وضعیت: {'🟢 فعال' if package.is_active else '⚪️ غیرفعال'}\n"
        f"توضیح: {package.description or '—'}"
    )
    await call.message.edit_text(text, reply_markup=kb.package_view(package))


@router.callback_query(kb.AdminCB.filter(F.action == "pkg_view"))
async def package_view(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    package = await session.get(Package, callback_data.arg)
    if package is None:
        await call.answer("یافت نشد.", show_alert=True)
        return
    await _render_package(call, session, package)
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "pkg_edit"))
async def package_edit(
    call: CallbackQuery, callback_data: kb.AdminCB, state: FSMContext
) -> None:
    await state.set_state(AdminFlow.package_field)
    await state.update_data(package_id=callback_data.arg, field=callback_data.field)
    labels = dict(kb.PKG_FIELDS)
    await call.message.answer(
        f"مقدار جدید برای «{labels.get(callback_data.field, callback_data.field)}» را بفرستید:"
    )
    await call.answer()


@router.message(AdminFlow.package_field)
async def package_edit_save(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    package = await session.get(Package, data.get("package_id", 0))
    field = data.get("field", "")
    if package is None:
        await state.clear()
        await message.answer("پکیج یافت نشد.")
        return

    value = (message.text or "").strip()
    numeric = {"traffic_gb", "price", "device_limit", "inbound_id"}
    if field in numeric:
        if not value.isdigit():
            await message.answer("⚠️ لطفاً فقط عدد بفرستید.")
            return
        setattr(package, field, int(value))
    else:
        setattr(package, field, value)
    await session.commit()
    await state.clear()
    await message.answer("✅ ذخیره شد.", reply_markup=kb.back_home())


@router.callback_query(kb.AdminCB.filter(F.action == "pkg_toggle"))
async def package_toggle(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    package = await session.get(Package, callback_data.arg)
    if package:
        package.is_active = not package.is_active
        await session.commit()
        await _render_package(call, session, package)
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "pkg_del"))
async def package_del(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    package = await session.get(Package, callback_data.arg)
    if package is None:
        await call.answer("یافت نشد.", show_alert=True)
        return
    await call.message.edit_text(
        f"🗑 حذف پکیج «{package.title}»؟",
        reply_markup=kb.confirm("pkg_del_yes", package.id, "pkg_view"),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "pkg_del_yes"))
async def package_del_yes(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    package = await session.get(Package, callback_data.arg)
    duration_id = package.duration_id if package else 0
    if package:
        await session.delete(package)
        await session.commit()
    await call.answer("حذف شد.")
    callback_data.arg = duration_id
    await duration_view(call, callback_data, session)


# ---------- کاربران ----------


@router.callback_query(kb.AdminCB.filter(F.action == "users"))
async def users_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.user_lookup)
    await call.message.answer(
        "🔎 شناسه عددی یا @یوزرنیم کاربر را بفرستید:"
    )
    await call.answer()


@router.message(AdminFlow.user_lookup)
async def users_lookup(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    query = (message.text or "").strip().lstrip("@")
    user: User | None = None
    if query.isdigit():
        user = await session.get(User, int(query))
    else:
        user = (
            await session.execute(select(User).where(User.username == query))
        ).scalar_one_or_none()
    if user is None:
        await message.answer("کاربر یافت نشد.", reply_markup=kb.back_home())
        return
    await _render_user(message, session, user)


async def _render_user(message: Message, session: AsyncSession, user: User) -> None:
    svc_count = int(
        (await session.execute(
            select(func.count(Service.id)).where(Service.user_id == user.id)
        )).scalar() or 0
    )
    order_count = int(
        (await session.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user.id, Order.status == OrderStatus.APPROVED
            )
        )).scalar() or 0
    )
    uname = f"@{user.username}" if user.username else "—"
    text = (
        f"👤 <b>{user.first_name or ''}</b> ({uname})\n"
        f"🆔 <code>{user.id}</code>\n"
        f"وضعیت: {'⛔️ مسدود' if user.is_blocked else '🟢 عادی'}\n"
        f"امتیاز: {fa_digits(user.points)}\n"
        f"سرویس‌ها: {fa_digits(svc_count)} | خریدهای موفق: {fa_digits(order_count)}\n"
        f"تست استفاده‌شده: {'بله' if user.trial_used else 'خیر'}"
    )
    await message.answer(text, reply_markup=kb.user_actions(user.id, user.is_blocked))


@router.callback_query(kb.AdminCB.filter(F.action == "user_block"))
async def user_block(call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession) -> None:
    user = await session.get(User, callback_data.arg)
    if user:
        user.is_blocked = True
        await session.commit()
    await call.answer("کاربر مسدود شد.")
    await _render_user(call.message, session, user)


@router.callback_query(kb.AdminCB.filter(F.action == "user_unblock"))
async def user_unblock(call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession) -> None:
    user = await session.get(User, callback_data.arg)
    if user:
        user.is_blocked = False
        await session.commit()
    await call.answer("رفع مسدودی شد.")
    await _render_user(call.message, session, user)


@router.callback_query(kb.AdminCB.filter(F.action == "user_gift"))
async def user_gift_prompt(
    call: CallbackQuery, callback_data: kb.AdminCB, state: FSMContext
) -> None:
    await state.set_state(AdminFlow.gift_days)
    await state.update_data(user_id=callback_data.arg)
    await call.message.answer(
        "تعداد امتیاز هدیه را بفرستید (به کاربر اضافه می‌شود):"
    )
    await call.answer()


@router.message(AdminFlow.gift_days)
async def user_gift_save(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()
    value = (message.text or "").strip()
    if not value.lstrip("-").isdigit():
        await message.answer("⚠️ یک عدد بفرستید.")
        return
    user = await session.get(User, data.get("user_id", 0))
    if user is None:
        await message.answer("کاربر یافت نشد.")
        return
    amount = int(value)
    await pts.add_points(session, user, amount, "admin_gift")
    try:
        await bot.send_message(
            user.id, f"🎁 مدیر {fa_digits(abs(amount))} امتیاز به شما "
            f"{'اضافه' if amount >= 0 else 'کسر'} کرد."
        )
    except Exception:  # noqa: BLE001
        pass
    await message.answer(
        f"✅ امتیاز کاربر به {fa_digits(user.points)} رسید.",
        reply_markup=kb.back_home(),
    )


# ---------- آمار ----------


@router.callback_query(kb.AdminCB.filter(F.action == "stats"))
async def stats(call: CallbackQuery, session: AsyncSession) -> None:
    users = int((await session.execute(select(func.count(User.id)))).scalar() or 0)
    active_svc = int(
        (await session.execute(
            select(func.count(Service.id)).where(Service.status == ServiceStatus.ACTIVE)
        )).scalar() or 0
    )
    pending = int(
        (await session.execute(
            select(func.count(Order.id)).where(Order.status == OrderStatus.AWAITING_APPROVAL)
        )).scalar() or 0
    )
    revenue = int(
        (await session.execute(
            select(func.coalesce(func.sum(Order.amount), 0)).where(
                Order.status == OrderStatus.APPROVED
            )
        )).scalar() or 0
    )
    sold = int(
        (await session.execute(
            select(func.count(Order.id)).where(Order.status == OrderStatus.APPROVED)
        )).scalar() or 0
    )
    text = (
        "📊 <b>آمار</b>\n\n"
        f"👥 کاربران: <b>{fa_digits(users)}</b>\n"
        f"🟢 سرویس‌های فعال: <b>{fa_digits(active_svc)}</b>\n"
        f"🧾 فروش موفق: <b>{fa_digits(sold)}</b>\n"
        f"⏳ در انتظار تأیید: <b>{fa_digits(pending)}</b>\n"
        f"💰 مجموع درآمد: <b>{money(revenue)} تومان</b>"
    )
    await call.message.edit_text(text, reply_markup=kb.back_home())
    await call.answer()


# ---------- تست اتصال پنل ----------


@router.callback_query(kb.AdminCB.filter(F.action == "ping"))
async def ping_panel(call: CallbackQuery) -> None:
    await call.answer("در حال بررسی...")
    try:
        await get_provider().ping()
        await call.message.edit_text("🟢 اتصال به پنل موفق بود.", reply_markup=kb.back_home())
    except VpnError as exc:
        await call.message.edit_text(
            f"🔴 اتصال ناموفق:\n<code>{exc}</code>", reply_markup=kb.back_home()
        )
    except Exception as exc:  # noqa: BLE001
        await call.message.edit_text(
            f"🔴 خطا:\n<code>{exc}</code>", reply_markup=kb.back_home()
        )


# ---------- پیام همگانی ----------


@router.callback_query(kb.AdminCB.filter(F.action == "broadcast"))
async def broadcast_prompt(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.broadcast)
    await call.message.answer(
        "📣 پیامی که می‌خواهید برای همه کاربران ارسال شود را بفرستید.\n"
        "(متن با فرمت HTML) — /cancel برای انصراف"
    )
    await call.answer()


@router.message(AdminFlow.broadcast, F.text)
async def broadcast_send(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot
) -> None:
    await state.clear()
    ids = list(
        (await session.execute(
            select(User.id).where(User.is_blocked.is_(False))
        )).scalars().all()
    )
    await message.answer(f"در حال ارسال به {fa_digits(len(ids))} کاربر...")
    sent = failed = 0
    for uid in ids:
        try:
            await bot.send_message(uid, message.html_text)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)  # جلوگیری از محدودیت نرخ تلگرام
    await message.answer(
        f"✅ ارسال شد: {fa_digits(sent)} | ناموفق: {fa_digits(failed)}",
        reply_markup=kb.back_home(),
    )
