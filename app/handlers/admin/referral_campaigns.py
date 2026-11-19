"""مدیریت کمپین‌های پاداش دعوت (پاداش کیف پول) — پنل ادمین."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Package, ReferralCampaign, ReferralReward, utcnow
from app.filters import IsAdmin
from app.states import RefCampaignFlow
from app.utils.formatting import fa_digits, money

logger = logging.getLogger(__name__)
router = Router(name="admin_referral_campaigns")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _num(text: str) -> int | None:
    raw = text.translate(_FA).replace(",", "").replace("٬", "").strip()
    return int(raw) if raw.isdigit() else None


async def _pkg_label(session: AsyncSession, package_id: int | None) -> str:
    if not package_id:
        return "همه پکیج‌ها"
    p = await session.get(Package, package_id)
    return p.title if p else f"پکیج #{package_id} (حذف‌شده)"


async def _detail(session: AsyncSession, c: ReferralCampaign) -> str:
    cap = fa_digits(c.max_rewards) if c.max_rewards else "نامحدود"
    until = c.valid_until.strftime("%Y-%m-%d") if c.valid_until else "نامحدود"
    total = await session.scalar(
        select(func.coalesce(func.sum(ReferralReward.amount), 0)).where(
            ReferralReward.campaign_id == c.id
        )
    )
    return (
        f"🎯 <b>{c.title}</b> (#{c.id})\n"
        f"وضعیت: {'🟢 فعال' if c.is_active else '⚪️ غیرفعال'}\n\n"
        f"💰 پاداش هر دعوت: <b>{money(c.reward_amount)} تومان</b>\n"
        f"📦 سرویس مشمول: {await _pkg_label(session, c.package_id)}\n"
        f"🔢 پاداش داده‌شده: {fa_digits(c.rewarded_count)} / {cap}\n"
        f"💸 مجموع پرداختی: {money(total or 0)} تومان\n"
        f"⏳ اعتبار تا: {until}\n\n"
        f"<i>با تأیید اولین خرید مشمول دعوت‌شده، مبلغ به کیف پول دعوت‌کننده "
        f"اضافه می‌شود (یک‌بار برای هر دعوت‌شده).</i>"
    )


def _detail_kb(c: ReferralCampaign):
    b = InlineKeyboardBuilder()
    b.button(
        text="⚪️ غیرفعال کردن" if c.is_active else "🟢 فعال کردن",
        callback_data=f"rc:toggle:{c.id}",
    )
    b.button(text="🗑 حذف", callback_data=f"rc:delask:{c.id}")
    b.button(text="🔙 بازگشت", callback_data="rc:list")
    b.adjust(2, 1)
    return b.as_markup()


@router.callback_query(F.data == "rc:list")
async def rc_list(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    camps = (
        await session.scalars(select(ReferralCampaign).order_by(ReferralCampaign.id.desc()))
    ).all()
    b = InlineKeyboardBuilder()
    for c in camps:
        b.button(
            text=f"{'🟢' if c.is_active else '⚪️'} {c.title} — {money(c.reward_amount)}",
            callback_data=f"rc:view:{c.id}",
        )
    b.button(text="➕ کمپین جدید", callback_data="rc:new")
    b.button(text="🔙 پنل مدیریت", callback_data="rc:home")
    b.adjust(1)
    text = (
        "🎯 <b>کمپین‌های پاداش دعوت</b>\n\n"
        "وقتی کاربرِ دعوت‌شده سرویس بخرد، مبلغ پاداش به <b>کیف پول دعوت‌کننده</b> "
        "اضافه می‌شود."
        + ("" if camps else "\n\nهنوز کمپینی ساخته نشده.")
    )
    await call.message.edit_text(text, reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "rc:home")
async def rc_home(call: CallbackQuery) -> None:
    from app.keyboards import admin as kb

    await call.message.edit_text("🛠 <b>پنل مدیریت</b>", reply_markup=kb.home())
    await call.answer()


@router.callback_query(F.data.startswith("rc:view:"))
async def rc_view(call: CallbackQuery, session: AsyncSession) -> None:
    c = await session.get(ReferralCampaign, int(call.data.split(":")[2]))
    if c is None:
        await call.answer("کمپین یافت نشد.", show_alert=True)
        return
    await call.message.edit_text(await _detail(session, c), reply_markup=_detail_kb(c))
    await call.answer()


@router.callback_query(F.data.startswith("rc:toggle:"))
async def rc_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    c = await session.get(ReferralCampaign, int(call.data.split(":")[2]))
    if c is None:
        await call.answer("کمپین یافت نشد.", show_alert=True)
        return
    c.is_active = not c.is_active
    await session.commit()
    await call.message.edit_text(await _detail(session, c), reply_markup=_detail_kb(c))
    await call.answer("فعال شد" if c.is_active else "غیرفعال شد")


@router.callback_query(F.data.startswith("rc:delask:"))
async def rc_del_ask(call: CallbackQuery) -> None:
    cid = call.data.split(":")[2]
    b = InlineKeyboardBuilder()
    b.button(text="✅ بله، حذف شود", callback_data=f"rc:del:{cid}")
    b.button(text="🔙 خیر", callback_data=f"rc:view:{cid}")
    b.adjust(2)
    await call.message.edit_text(
        "⚠️ کمپین و سابقه پاداش‌های آن حذف می‌شود (مبالغ پرداخت‌شده در کیف پول‌ها "
        "باقی می‌ماند). مطمئنید؟",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("rc:del:"))
async def rc_del(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    c = await session.get(ReferralCampaign, int(call.data.split(":")[2]))
    if c is not None:
        await session.delete(c)
        await session.commit()
    await call.answer("حذف شد")
    await rc_list(call, session, state)


# ───────────────────────── ساخت کمپین ─────────────────────────

@router.callback_query(F.data == "rc:new")
async def rc_new(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    pkgs = (
        await session.scalars(
            select(Package).where(Package.is_active.is_(True)).order_by(Package.sort_order, Package.id)
        )
    ).all()
    b = InlineKeyboardBuilder()
    b.button(text="📦 همه پکیج‌ها", callback_data="rc:pkg:0")
    for p in pkgs:
        b.button(text=f"{p.title} — {money(p.price)}", callback_data=f"rc:pkg:{p.id}")
    b.button(text="🔙 انصراف", callback_data="rc:list")
    b.adjust(1)
    await call.message.edit_text(
        "🎯 <b>کمپین جدید</b>\n\nمرحله ۱/۴ — خرید کدام سرویس باید پاداش بدهد؟",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("rc:pkg:"))
async def rc_pick_pkg(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RefCampaignFlow.title)
    await state.update_data(package_id=int(call.data.split(":")[2]) or None)
    await call.message.answer("مرحله ۲/۴ — عنوان کمپین را بنویسید (مثال: «دعوت ویژه»):")
    await call.answer()


@router.message(RefCampaignFlow.title, F.text)
async def rc_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not (2 <= len(title) <= 100):
        await message.answer("❌ عنوان باید بین ۲ تا ۱۰۰ کاراکتر باشد:")
        return
    await state.update_data(title=title)
    await state.set_state(RefCampaignFlow.reward)
    await message.answer("مرحله ۳/۴ — مبلغ پاداش (تومان) که به کیف پول دعوت‌کننده برود:")


@router.message(RefCampaignFlow.reward, F.text)
async def rc_reward(message: Message, state: FSMContext) -> None:
    v = _num(message.text)
    if not v or v > 100_000_000:
        await message.answer("❌ یک مبلغ معتبر (بزرگ‌تر از صفر) وارد کنید:")
        return
    await state.update_data(reward=v)
    await state.set_state(RefCampaignFlow.max_rewards)
    await message.answer(
        "حداکثر تعداد کل پاداش‌های این کمپین؟ (۰ = نامحدود)"
    )


@router.message(RefCampaignFlow.max_rewards, F.text)
async def rc_max(message: Message, state: FSMContext) -> None:
    v = _num(message.text)
    if v is None:
        await message.answer("❌ عدد ۰ یا بزرگ‌تر وارد کنید:")
        return
    await state.update_data(max_rewards=v)
    await state.set_state(RefCampaignFlow.valid_days)
    await message.answer("مرحله ۴/۴ — کمپین چند روز معتبر باشد؟ (۰ = نامحدود)")


@router.message(RefCampaignFlow.valid_days, F.text)
async def rc_days(message: Message, state: FSMContext, session: AsyncSession) -> None:
    days = _num(message.text)
    if days is None:
        await message.answer("❌ عدد ۰ یا بزرگ‌تر وارد کنید:")
        return
    d = await state.get_data()
    await state.clear()
    c = ReferralCampaign(
        title=d["title"],
        reward_amount=d["reward"],
        package_id=d.get("package_id"),
        max_rewards=d.get("max_rewards", 0),
        valid_until=utcnow() + timedelta(days=days) if days else None,
        is_active=True,
    )
    session.add(c)
    await session.commit()
    await message.answer(
        "✅ کمپین ساخته و فعال شد.\n\n" + await _detail(session, c),
        reply_markup=_detail_kb(c),
    )
