"""مدیریت تخفیف‌ها و پیشنهادهای ویژه از پنل ادمین."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OfferType
from app.filters import IsAdmin
from app.keyboards import admin as kb
from app.services import offers_service as svc
from app.states import AdminFlow
from app.utils.formatting import fa_digits, jalali_date, money, traffic

logger = logging.getLogger(__name__)
router = Router(name="admin_offers")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

# نگاشت نوع تخفیف → برچسب فارسی
TYPE_LABELS = {
    OfferType.PERCENT: "درصد تخفیف",
    OfferType.FIXED: "مبلغ ثابت تخفیف",
    OfferType.EXTRA_TRAFFIC: "حجم اضافه",
}
TYPE_KEYS = {
    "1": OfferType.PERCENT,
    "2": OfferType.FIXED,
    "3": OfferType.EXTRA_TRAFFIC,
}


def _offer_detail(offer) -> str:
    """متن کامل یک تخفیف برای پنل ادمین."""
    status = "🟢 فعال" if offer.is_active else "⚪️ غیرفعال"
    type_label = TYPE_LABELS.get(offer.offer_type, str(offer.offer_type))

    if offer.offer_type == OfferType.PERCENT:
        value_str = f"{fa_digits(offer.value)}٪ تخفیف"
    elif offer.offer_type == OfferType.FIXED:
        value_str = f"{money(offer.value)} تومان تخفیف"
    else:
        value_str = f"{traffic(offer.value)} حجم اضافه"

    uses = f"{fa_digits(offer.used_count)}"
    if offer.max_uses > 0:
        uses += f" / {fa_digits(offer.max_uses)}"
    else:
        uses += " (نامحدود)"

    lines = [
        f"🏷 <b>{offer.title}</b>",
        f"شناسه: #{offer.id}  |  وضعیت: {status}",
        "",
        f"نوع: {type_label}",
        f"مقدار: <b>{value_str}</b>",
        f"کد: <code>{offer.code or '—'}</code> {'(بدون کد = خودکار)' if not offer.code else ''}",
        f"استفاده شده: {uses}",
    ]

    if offer.per_user > 0:
        lines.append(f"محدودیت هر کاربر: {fa_digits(offer.per_user)} بار")

    if offer.valid_from or offer.valid_until:
        lines.append(
            f"بازه زمانی: {jalali_date(offer.valid_from)} تا {jalali_date(offer.valid_until)}"
        )
    else:
        lines.append("بازه زمانی: نامحدود")

    if offer.package_id:
        lines.append(f"فقط پکیج: #{offer.package_id}")
    if offer.duration_id:
        lines.append(f"فقط مدت: #{offer.duration_id}")

    if offer.description:
        lines.append(f"\n{offer.description}")

    return "\n".join(lines)


# ───────────────────── لیست تخفیف‌ها ─────────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "offers"))
async def offers_list(call: CallbackQuery, session: AsyncSession) -> None:
    all_offers = await svc.get_all_offers(session)
    if not all_offers:
        text = "🏷 <b>تخفیف‌ها</b>\n\nهنوز هیچ تخفیفی ساخته نشده."
    else:
        lines = [f"🏷 <b>تخفیف‌ها</b> ({fa_digits(len(all_offers))} مورد)", ""]
        for o in all_offers:
            st = "🟢" if o.is_active else "⚪️"
            code_part = f"  [<code>{o.code}</code>]" if o.code else "  [خودکار]"
            uses = f"{o.used_count}/{o.max_uses}" if o.max_uses else f"{o.used_count}/∞"
            lines.append(f"{st} #{o.id} {o.title}{code_part}  ✉️{uses}")
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=kb.offers_list_kb(all_offers))
    await call.answer()


# ───────────────────── مشاهده یک تخفیف ──────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "offer_view"))
async def offer_view(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    offer = await svc.get_offer(session, callback_data.arg)
    if offer is None:
        await call.answer("تخفیف یافت نشد.", show_alert=True)
        return
    await call.message.edit_text(
        _offer_detail(offer),
        reply_markup=kb.offer_detail_kb(offer),
    )
    await call.answer()


# ───────────────────── فعال/غیرفعال کردن ─────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "offer_toggle"))
async def offer_toggle(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    offer = await svc.toggle_offer(session, callback_data.arg)
    if offer is None:
        await call.answer("تخفیف یافت نشد.", show_alert=True)
        return
    status = "فعال" if offer.is_active else "غیرفعال"
    await call.answer(f"تخفیف {status} شد.")
    await call.message.edit_text(
        _offer_detail(offer),
        reply_markup=kb.offer_detail_kb(offer),
    )


# ───────────────────── حذف تخفیف ─────────────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "offer_del_confirm"))
async def offer_del_confirm(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    offer = await svc.get_offer(session, callback_data.arg)
    if offer is None:
        await call.answer("تخفیف یافت نشد.", show_alert=True)
        return
    await call.message.edit_text(
        f"⚠️ آیا مطمئنید می‌خواهید تخفیف <b>«{offer.title}»</b> را حذف کنید؟",
        reply_markup=kb.confirm(
            action="offer_del_do",
            arg=callback_data.arg,
            back_action="offer_view",
        ),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "offer_del_do"))
async def offer_del_do(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    await svc.delete_offer(session, callback_data.arg)
    await call.answer("تخفیف حذف شد.")
    # برگشت به لیست
    all_offers = await svc.get_all_offers(session)
    lines = [f"🏷 <b>تخفیف‌ها</b>  (پس از حذف)", ""]
    for o in all_offers:
        st = "🟢" if o.is_active else "⚪️"
        lines.append(f"{st} #{o.id} {o.title}")
    text = "\n".join(lines) if all_offers else "🏷 هیچ تخفیفی باقی نمانده."
    await call.message.edit_text(text, reply_markup=kb.offers_list_kb(all_offers))


# ────────────────────── ساخت تخفیف جدید ─────────────────────────────
# جریان چند مرحله‌ای:
# offer_add → (state: offer_title) → offer_type → offer_value
#           → offer_code → offer_max_uses → offer_per_user → offer_valid_days → ذخیره

@router.callback_query(kb.AdminCB.filter(F.action == "offer_add"))
async def offer_add_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.offer_title)
    await state.update_data(offer_data={})
    await call.message.answer(
        "🏷 <b>ساخت تخفیف جدید</b>\n\n"
        "مرحله ۱/۷ — عنوان تخفیف را بنویسید:\n"
        "(مثال: «جشن نوروز» یا «پیشنهاد ویژه هفته»)"
    )
    await call.answer()


@router.message(AdminFlow.offer_title)
async def offer_step_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("عنوان خیلی کوتاه است. دوباره وارد کنید:")
        return
    await state.update_data(offer_data={"title": title})
    await state.set_state(AdminFlow.offer_type)
    await message.answer(
        "مرحله ۲/۷ — نوع تخفیف را انتخاب کنید:\n\n"
        "1️⃣ درصد تخفیف (مثال: ۲۰٪ تخفیف)\n"
        "2️⃣ مبلغ ثابت تخفیف (مثال: ۵۰،۰۰۰ تومان)\n"
        "3️⃣ حجم اضافه (مثال: ۵ گیگ اضافه)\n\n"
        "عدد ۱، ۲ یا ۳ را بفرستید:"
    )


@router.message(AdminFlow.offer_type)
async def offer_step_type(message: Message, state: FSMContext) -> None:
    key = message.text.strip()
    if key not in TYPE_KEYS:
        await message.answer("لطفاً عدد ۱، ۲ یا ۳ بفرستید:")
        return
    offer_type = TYPE_KEYS[key]
    data = (await state.get_data()).get("offer_data", {})
    data["offer_type"] = offer_type.value
    await state.update_data(offer_data=data)
    await state.set_state(AdminFlow.offer_value)

    if offer_type == OfferType.PERCENT:
        prompt = "مرحله ۳/۷ — درصد تخفیف را وارد کنید (عدد ۱ تا ۱۰۰):"
    elif offer_type == OfferType.FIXED:
        prompt = "مرحله ۳/۷ — مبلغ تخفیف به تومان را وارد کنید (بدون خط فاصله):"
    else:
        prompt = "مرحله ۳/۷ — حجم اضافه را به مگابایت وارد کنید:\n(مثال: ۵۱۲۰ برای ۵ گیگ)"
    await message.answer(prompt)


@router.message(AdminFlow.offer_value)
async def offer_step_value(message: Message, state: FSMContext) -> None:
    try:
        value = int(message.text.strip().replace(",", "").replace("،", ""))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ عدد معتبری وارد کنید:")
        return

    data = (await state.get_data()).get("offer_data", {})
    offer_type = OfferType(data.get("offer_type", OfferType.PERCENT.value))
    if offer_type == OfferType.PERCENT and value > 100:
        await message.answer("❌ درصد تخفیف نمی‌تواند بیشتر از ۱۰۰ باشد:")
        return

    data["value"] = value
    await state.update_data(offer_data=data)
    await state.set_state(AdminFlow.offer_code)
    await message.answer(
        "مرحله ۴/۷ — کد تخفیف:\n\n"
        "• اگر می‌خواهید کاربران با وارد کردن یک کد تخفیف بگیرند، کد را بنویسید.\n"
        "• اگر می‌خواهید تخفیف <b>خودکار</b> برای همه اعمال شود، عبارت «auto» را بفرستید.\n\n"
        "کد فقط حروف و اعداد انگلیسی (مثال: NOROUZ1404)"
    )


@router.message(AdminFlow.offer_code)
async def offer_step_code(message: Message, state: FSMContext) -> None:
    raw = message.text.strip().upper()
    code: str | None = None
    if raw != "AUTO":
        # اعتبارسنجی کد: فقط حروف/عدد، ۳ تا ۲۰ کاراکتر
        if not raw.isalnum() or not (3 <= len(raw) <= 20):
            await message.answer(
                "❌ کد باید بین ۳ تا ۲۰ کاراکتر و فقط حروف/اعداد انگلیسی باشد. دوباره وارد کنید:"
            )
            return
        code = raw

    data = (await state.get_data()).get("offer_data", {})
    data["code"] = code
    await state.update_data(offer_data=data)
    await state.set_state(AdminFlow.offer_max_uses)
    await message.answer(
        "مرحله ۵/۷ — حداکثر تعداد کل استفاده:\n\n"
        "• برای نامحدود عدد ۰ را بفرستید.\n"
        "• مثال: ۱۰۰ یعنی این تخفیف در مجموع ۱۰۰ بار قابل استفاده است."
    )


@router.message(AdminFlow.offer_max_uses)
async def offer_step_max_uses(message: Message, state: FSMContext) -> None:
    try:
        max_uses = int(message.text.strip())
        if max_uses < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ عدد ۰ یا بزرگ‌تر وارد کنید:")
        return

    data = (await state.get_data()).get("offer_data", {})
    data["max_uses"] = max_uses
    await state.update_data(offer_data=data)
    await state.set_state(AdminFlow.offer_per_user)
    await message.answer(
        "مرحله ۶/۷ — حداکثر استفاده توسط هر کاربر:\n\n"
        "• برای نامحدود عدد ۰ را بفرستید.\n"
        "• مثال: ۱ یعنی هر کاربر فقط یک بار می‌تواند استفاده کند."
    )


@router.message(AdminFlow.offer_per_user)
async def offer_step_per_user(message: Message, state: FSMContext) -> None:
    try:
        per_user = int(message.text.strip())
        if per_user < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ عدد ۰ یا بزرگ‌تر وارد کنید:")
        return

    data = (await state.get_data()).get("offer_data", {})
    data["per_user"] = per_user
    await state.update_data(offer_data=data)
    await state.set_state(AdminFlow.offer_valid_days)
    await message.answer(
        "مرحله ۷/۷ — مدت اعتبار:\n\n"
        "• برای نامحدود عدد ۰ را بفرستید.\n"
        "• مثال: ۷ یعنی این تخفیف تا ۷ روز دیگر معتبر است."
    )


@router.message(AdminFlow.offer_valid_days)
async def offer_step_valid_days(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ عدد ۰ یا بزرگ‌تر وارد کنید:")
        return

    data = (await state.get_data()).get("offer_data", {})
    await state.clear()

    now = datetime.now(timezone.utc)
    valid_from = now if days > 0 else None
    valid_until = now + timedelta(days=days) if days > 0 else None

    offer_type = OfferType(data.get("offer_type", OfferType.PERCENT.value))

    offer = await svc.create_offer(
        session,
        title=data["title"],
        offer_type=offer_type,
        value=data["value"],
        code=data.get("code"),
        max_uses=data.get("max_uses", 0),
        per_user=data.get("per_user", 0),
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=True,
    )

    # پیام تأیید
    code_str = f"<code>{offer.code}</code>" if offer.code else "خودکار (بدون کد)"
    validity = f"{fa_digits(days)} روز" if days > 0 else "نامحدود"
    await message.answer(
        f"✅ تخفیف جدید ساخته شد!\n\n"
        f"🏷 عنوان: <b>{offer.title}</b>\n"
        f"کد: {code_str}\n"
        f"نوع: {TYPE_LABELS.get(offer_type)}\n"
        f"مقدار: {data['value']}\n"
        f"اعتبار: {validity}\n\n"
        f"تخفیف هم‌اکنون فعال است.",
        reply_markup=kb.offer_detail_kb(offer),
    )
    logger.info("admin created offer #%s: %s", offer.id, offer.title)
