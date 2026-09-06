"""گزارش فعالیت کاربران برای ادمین."""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserActivity
from app.keyboards import admin as kb
from app.services import activity_service
from app.states import ActivitySearch
from app.utils.formatting import fa_digits, jalali_date

router = Router(name="admin_activity")


# برچسب فارسی هر نوع فعالیت
ACTION_LABELS: dict[str, str] = {
    "start": "شروع ربات",
    "menu": "باز کردن منو",
    "view_plans": "مشاهده پلن‌ها",
    "view_durations": "مشاهده مدت‌ها",
    "view_packages": "مشاهده پکیج‌ها",
    "select_package": "انتخاب پکیج",
    "initiate_buy": "شروع خرید",
    "view_services": "مشاهده سرویس‌ها",
    "view_config": "مشاهده کانفیگ",
    "copy_link": "کپی لینک",
    "regen_links": "بازسازی لینک",
    "view_points": "مشاهده امتیاز",
    "redeem_points": "تبدیل امتیاز",
    "invite": "دعوت دوستان",
    "trial": "تست رایگان",
    "guide": "راهنما",
    "support": "پشتیبانی",
}


def _action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def _format_activity(act: UserActivity) -> str:
    """یک رکورد فعالیت را برای نمایش فرمت می‌کند."""
    label = _action_label(act.action)
    time_str = jalali_date(act.created_at)

    details = ""
    if act.details:
        try:
            details_json = json.loads(act.details)
            if details_json:
                parts = [f"{k}: {v}" for k, v in details_json.items()]
                details = f" ({', '.join(parts)})"
        except (json.JSONDecodeError, TypeError):
            pass

    return f"• {label}{details}\n  <i>{time_str}</i>"


# ───────────────────────────── صفحه اصلی ─────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "activity"))
async def show_activity_home(call: CallbackQuery, session: AsyncSession) -> None:
    """صفحه اصلی گزارش فعالیت — آمار ۷ روز گذشته."""
    stats = await activity_service.get_activity_stats(session, days=7)

    lines = [
        "📈 <b>گزارش فعالیت کاربران</b>",
        "",
        "📅 <b>آمار ۷ روز گذشته:</b>",
        f"  • تعداد کل فعالیت‌ها: <b>{fa_digits(stats['total'])}</b>",
        f"  • کاربران فعال: <b>{fa_digits(stats['active_users'])}</b>",
        "",
        "🔝 <b>پرتکرارترین فعالیت‌ها:</b>",
    ]

    if stats["action_counts"]:
        for action, count in list(stats["action_counts"].items())[:10]:
            lines.append(f"  • {_action_label(action)}: <b>{fa_digits(count)}</b>")
    else:
        lines.append("  هنوز هیچ فعالیتی ثبت نشده.")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=kb.activity_home_kb(),
    )
    await call.answer()


# ──────────────────────── آخرین فعالیت‌ها ────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "activity_recent"))
async def show_recent_activities(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش ۳۰ فعالیت اخیر، گروه‌بندی شده بر اساس کاربر."""
    activities = await activity_service.get_recent_activities(session, limit=30)

    if not activities:
        await call.message.edit_text(
            "📭 هیچ فعالیتی ثبت نشده است.",
            reply_markup=kb.back_activity(),
        )
        await call.answer()
        return

    lines = ["📋 <b>آخرین ۳۰ فعالیت</b>", ""]

    # گروه‌بندی بر اساس user_id برای خوانایی بیشتر
    current_uid: int | None = None
    bucket: list[UserActivity] = []

    async def _flush(uid: int, bucket: list[UserActivity]) -> None:
        user = await session.get(User, uid)
        name = (user.first_name or "ناشناس") if user else "ناشناس"
        uname = (f"@{user.username} " if user and user.username else "")
        lines.append(f"👤 <b>{name}</b> {uname}(<code>{uid}</code>):")
        for act in bucket[:5]:          # حداکثر ۵ تا از هر کاربر
            lines.append(_format_activity(act))
        lines.append("")

    for act in activities:
        if act.user_id != current_uid:
            if bucket and current_uid is not None:
                await _flush(current_uid, bucket)
            current_uid = act.user_id
            bucket = []
        bucket.append(act)

    if bucket and current_uid is not None:
        await _flush(current_uid, bucket)

    await call.message.edit_text(
        "\n".join(lines)[:4000],
        reply_markup=kb.back_activity(),
    )
    await call.answer()


# ─────────────────────── فعالیت یک کاربر (از طریق callback) ──────────

@router.callback_query(kb.AdminCB.filter(F.action == "activity_user"))
async def show_user_activity(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    """نمایش خلاصه و جزئیات فعالیت‌های یک کاربر خاص."""
    user_id = callback_data.arg
    await _render_user_activity(call.message, session, user_id, edit=True)
    await call.answer()


# ────────────────────────── جستجوی کاربر ────────────────────────────

@router.callback_query(kb.AdminCB.filter(F.action == "activity_search"))
async def activity_search_prompt(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست آیدی عددی کاربر برای جستجوی فعالیت."""
    await call.message.edit_text(
        "🔍 آیدی عددی کاربر را وارد کنید:",
        reply_markup=kb.back_activity(),
    )
    await state.set_state(ActivitySearch.waiting_user_id)
    await call.answer()


@router.message(ActivitySearch.waiting_user_id)
async def activity_search_result(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """دریافت آیدی و نمایش گزارش کاربر."""
    await state.clear()

    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ آیدی باید یک عدد صحیح باشد. دوباره امتحان کنید.",
            reply_markup=kb.back_activity(),
        )
        return

    user = await session.get(User, user_id)
    if user is None:
        await message.answer(
            f"❌ کاربری با آیدی <code>{user_id}</code> یافت نشد.",
            reply_markup=kb.back_activity(),
        )
        return

    await _render_user_activity(message, session, user_id, edit=False)


# ─────────────────────────── helper مشترک ────────────────────────────

async def _render_user_activity(
    target: Message, session: AsyncSession, user_id: int, *, edit: bool
) -> None:
    """متن گزارش فعالیت را می‌سازد و ارسال/ویرایش می‌کند."""
    user = await session.get(User, user_id)
    if user is None:
        text = f"❌ کاربر <code>{user_id}</code> یافت نشد."
        if edit:
            await target.edit_text(text, reply_markup=kb.back_activity())
        else:
            await target.answer(text, reply_markup=kb.back_activity())
        return

    summary = await activity_service.get_user_activity_summary(session, user_id, days=30)

    uname = f"@{user.username} " if user.username else ""
    lines = [
        f"👤 <b>{user.first_name or 'کاربر'}</b> {uname}(<code>{user_id}</code>)",
        "",
        "📊 <b>آمار ۳۰ روز گذشته:</b>",
        f"  • کل فعالیت‌ها: <b>{fa_digits(summary['total'])}</b>",
    ]

    if summary["last_activity_at"]:
        lines.append(f"  • آخرین فعالیت: {jalali_date(summary['last_activity_at'])}")

    if summary["action_counts"]:
        lines.append("")
        lines.append("📌 <b>نوع فعالیت‌ها:</b>")
        for action, count in summary["action_counts"].items():
            lines.append(f"  • {_action_label(action)}: {fa_digits(count)}")
    else:
        lines.append("  هیچ فعالیتی در این بازه ثبت نشده.")

    # ۱۰ فعالیت اخیر با جزئیات
    recent = await activity_service.get_user_activities(session, user_id, limit=10)
    if recent:
        lines.append("")
        lines.append("🕐 <b>آخرین فعالیت‌ها:</b>")
        for act in recent:
            lines.append(_format_activity(act))

    text = "\n".join(lines)[:4000]
    if edit:
        await target.edit_text(text, reply_markup=kb.back_activity())
    else:
        await target.answer(text, reply_markup=kb.back_activity())
