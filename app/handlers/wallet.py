"""هندلر کیف داده — تقسیم سرویس و انتقال به کاربر دیگر."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Service, User
from app.handlers.delivery import send_config
from app.keyboards import inline
from app.services import activity_service as activity
from app.services import wallet_service as wallet
from app.states import WalletFlow
from app.texts import (
    BTN_EARN,
    MSG_CANCELLED,
    MSG_EARN_INTRO,
    MSG_WALLET_CONFIRM_OTHER,
    MSG_WALLET_CONFIRM_SELF,
    MSG_WALLET_ENTER_RECIPIENT,
    MSG_WALLET_ENTER_SIZE,
    MSG_WALLET_INTRO,
    MSG_WALLET_NO_SERVICE,
    MSG_WALLET_PROCESSING,
    MSG_WALLET_RECIPIENT_NOT_FOUND,
    MSG_WALLET_SELECT_TYPE,
    MSG_WALLET_SIZE_ERROR,
    MSG_WALLET_SUCCESS_OTHER,
    MSG_WALLET_SUCCESS_SELF,
)
from app.utils.formatting import days_left_text, fa_digits, jalali_date, traffic

logger = logging.getLogger(__name__)
router = Router(name="wallet")

# ─────────────────────── کمک‌های نمایشی ───────────────────────────


def _traffic(mb: int) -> str:
    return traffic(mb)


def _expires(service: Service) -> str:
    return jalali_date(service.expires_at)


# ══════════════════════════════════════════════════════════════════
#  ورود: دکمه «کسب درآمد»
# ══════════════════════════════════════════════════════════════════

@router.message(F.text == BTN_EARN)
async def earn_entry(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    services = await wallet.get_splittable_services(session, user.id)
    if not services:
        await message.answer(
            MSG_EARN_INTRO + "\n\n⚠️ در حال حاضر سرویس قابل تقسیمی ندارید.\n"
            "پس از خرید اشتراک می‌توانید از این قابلیت استفاده کنید."
        )
        return
    await message.answer(
        MSG_EARN_INTRO,
        reply_markup=inline.earn_open_kb(services),
    )
    await activity.log_activity(session, user.id, "earn_entry")


# ══════════════════════════════════════════════════════════════════
#  مرحله ۱: انتخاب سرویس والد
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "select_service"))
async def select_service(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    # اگر service_id=0 باشد یعنی «بازگشت» از صفحه بعدی زده شده
    if callback_data.service_id == 0:
        await state.clear()
        services = await wallet.get_splittable_services(session, user.id)
        if not services:
            await call.message.edit_text(MSG_WALLET_NO_SERVICE)
            await call.answer()
            return
        await call.message.edit_text(
            MSG_WALLET_INTRO,
            reply_markup=inline.wallet_services_kb(services),
        )
        await call.answer()
        return

    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    avail = wallet.available_mb(service)
    text = MSG_WALLET_SELECT_TYPE.format(
        title=service.title,
        available=_traffic(avail),
        expires=_expires(service),
    )
    await call.message.edit_text(
        text,
        reply_markup=inline.wallet_type_kb(service.id),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════
#  مرحله ۲: انتخاب نوع (برای خودم / دیگری)
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "set_type"))
async def set_type(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    avail = wallet.available_mb(service)
    text = MSG_WALLET_ENTER_SIZE.format(available=_traffic(avail))
    await call.message.edit_text(
        text,
        reply_markup=inline.wallet_size_kb(
            service_id=service.id,
            for_other=callback_data.for_other,
            available_mb_val=avail,
        ),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════
#  مرحله ۳الف: انتخاب حجم از دکمه‌های سریع
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "set_size"))
async def set_size_quick(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    allocated_mb = callback_data.allocated_mb
    err = await wallet.validate_split(session, service, allocated_mb, user.id)
    if err:
        await call.answer(err, show_alert=True)
        return

    await _show_confirm(
        call=call,
        session=session,
        user=user,
        state=state,
        service=service,
        allocated_mb=allocated_mb,
        for_other=callback_data.for_other,
        recipient_id=0,
    )


# ══════════════════════════════════════════════════════════════════
#  مرحله ۳ب: ورود مقدار دلخواه (متن)
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "enter_custom"))
async def ask_custom_size(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    service = await session.get(Service, callback_data.service_id)
    if service is None:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return
    avail = wallet.available_mb(service)
    await state.set_state(WalletFlow.entering_size)
    await state.update_data(
        service_id=callback_data.service_id,
        for_other=callback_data.for_other,
    )
    await call.message.edit_text(
        MSG_WALLET_ENTER_SIZE.format(available=_traffic(avail))
        + "\n\n✏️ مقدار دلخواه را تایپ کنید:"
    )
    await call.answer()


@router.message(WalletFlow.entering_size)
async def receive_custom_size(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    service_id = data.get("service_id", 0)
    for_other = data.get("for_other", 0)

    service = await session.get(Service, service_id)
    if service is None or service.user_id != user.id:
        await state.clear()
        await message.answer("سرویس یافت نشد.")
        return

    mb, parse_err = wallet.parse_size_input(message.text or "")
    if parse_err:
        await message.answer(MSG_WALLET_SIZE_ERROR.format(error=parse_err))
        return

    err = await wallet.validate_split(session, service, mb, user.id)
    if err:
        await message.answer(MSG_WALLET_SIZE_ERROR.format(error=err))
        return

    await state.clear()

    if for_other:
        # نیاز به آیدی گیرنده داریم
        await state.set_state(WalletFlow.entering_recipient)
        await state.update_data(service_id=service_id, allocated_mb=mb, for_other=1)
        await message.answer(MSG_WALLET_ENTER_RECIPIENT)
    else:
        # تأیید مستقیم برای خودم
        avail = wallet.available_mb(service)
        remainder = avail - mb
        text = MSG_WALLET_CONFIRM_SELF.format(
            parent_title=service.title,
            allocated=_traffic(mb),
            remainder=_traffic(remainder),
            expires=_expires(service),
        )
        await message.answer(
            text,
            reply_markup=inline.wallet_confirm_kb(
                service_id=service_id,
                for_other=0,
                allocated_mb=mb,
            ),
        )


# ══════════════════════════════════════════════════════════════════
#  کمک: نمایش صفحه تأیید (از quick-size یا custom)
# ══════════════════════════════════════════════════════════════════

async def _show_confirm(
    *,
    call: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    service: Service,
    allocated_mb: int,
    for_other: int,
    recipient_id: int,
) -> None:
    avail = wallet.available_mb(service)
    remainder = avail - allocated_mb

    if for_other and recipient_id == 0:
        # باید آیدی گیرنده گرفته شود — وارد state می‌کنیم
        await state.set_state(WalletFlow.entering_recipient)
        await state.update_data(
            service_id=service.id,
            allocated_mb=allocated_mb,
            for_other=1,
        )
        await call.message.edit_text(MSG_WALLET_ENTER_RECIPIENT)
        await call.answer()
        return

    if for_other and recipient_id:
        recipient = await wallet.get_user_by_telegram_id(session, recipient_id)
        r_name = (
            recipient.first_name or str(recipient_id)
            if recipient else str(recipient_id)
        )
        text = MSG_WALLET_CONFIRM_OTHER.format(
            parent_title=service.title,
            allocated=_traffic(allocated_mb),
            remainder=_traffic(remainder),
            expires=_expires(service),
            recipient_name=r_name,
            recipient_id=recipient_id,
        )
    else:
        text = MSG_WALLET_CONFIRM_SELF.format(
            parent_title=service.title,
            allocated=_traffic(allocated_mb),
            remainder=_traffic(remainder),
            expires=_expires(service),
        )

    await call.message.edit_text(
        text,
        reply_markup=inline.wallet_confirm_kb(
            service_id=service.id,
            for_other=for_other,
            allocated_mb=allocated_mb,
            recipient_id=recipient_id,
        ),
    )
    await call.answer()


# ══════════════════════════════════════════════════════════════════
#  مرحله ۴ (انتقال): ورود آیدی گیرنده
# ══════════════════════════════════════════════════════════════════

@router.message(WalletFlow.entering_recipient)
async def receive_recipient(
    message: Message,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    service_id = data.get("service_id", 0)
    allocated_mb = data.get("allocated_mb", 0)

    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(MSG_WALLET_RECIPIENT_NOT_FOUND)
        return

    recipient_id = int(raw)
    if recipient_id == user.id:
        await message.answer(
            "❌ نمی‌توانید به خودتان انتقال دهید. "
            "از گزینه «ساخت کانفیگ جدید برای خودم» استفاده کنید."
        )
        return

    recipient = await wallet.get_user_by_telegram_id(session, recipient_id)
    if recipient is None:
        await message.answer(MSG_WALLET_RECIPIENT_NOT_FOUND)
        return

    service = await session.get(Service, service_id)
    if service is None or service.user_id != user.id:
        await state.clear()
        await message.answer("سرویس یافت نشد.")
        return

    await state.clear()

    avail = wallet.available_mb(service)
    remainder = avail - allocated_mb
    r_name = recipient.first_name or str(recipient_id)
    text = MSG_WALLET_CONFIRM_OTHER.format(
        parent_title=service.title,
        allocated=_traffic(allocated_mb),
        remainder=_traffic(remainder),
        expires=_expires(service),
        recipient_name=r_name,
        recipient_id=recipient_id,
    )
    await message.answer(
        text,
        reply_markup=inline.wallet_confirm_kb(
            service_id=service_id,
            for_other=1,
            allocated_mb=allocated_mb,
            recipient_id=recipient_id,
        ),
    )


# ══════════════════════════════════════════════════════════════════
#  مرحله نهایی: تأیید و اجرا
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "confirm"))
async def confirm_split(
    call: CallbackQuery,
    callback_data: inline.WalletCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    await state.clear()

    service = await session.get(Service, callback_data.service_id)
    if service is None or service.user_id != user.id:
        await call.answer("سرویس یافت نشد.", show_alert=True)
        return

    allocated_mb = callback_data.allocated_mb
    for_other = bool(callback_data.for_other)
    recipient_id = callback_data.recipient_id

    # تعیین گیرنده
    if for_other:
        recipient = await wallet.get_user_by_telegram_id(session, recipient_id)
        if recipient is None:
            await call.answer("کاربر گیرنده یافت نشد.", show_alert=True)
            return
    else:
        recipient = user

    await call.message.edit_text(MSG_WALLET_PROCESSING)

    try:
        child = await wallet.do_split(
            session,
            parent=service,
            allocated_mb=allocated_mb,
            recipient=recipient,
            title=f"کانفیگ {_traffic(allocated_mb)}",
            owner_id=user.id,
        )
    except wallet.SplitError as exc:
        await call.message.edit_text(f"❌ {exc}")
        await call.answer()
        return

    # به‌روزرسانی موجودی نمایش‌داده‌شده
    await session.refresh(service)
    remainder = service.traffic_mb

    if for_other:
        r_name = recipient.first_name or str(recipient_id)
        await call.message.edit_text(
            MSG_WALLET_SUCCESS_OTHER.format(
                allocated=_traffic(allocated_mb),
                recipient_name=r_name,
                remainder=_traffic(remainder),
            )
        )
        # ارسال کانفیگ به گیرنده
        try:
            await bot.send_message(
                recipient_id,
                f"🎁 یک کانفیگ جدید ({_traffic(allocated_mb)}) "
                f"از طرف یک کاربر برای شما ساخته شد!",
            )
            await send_config(bot, recipient_id, child, session)
        except Exception:
            logger.exception("failed delivering split config to user %s", recipient_id)
    else:
        await call.message.edit_text(
            MSG_WALLET_SUCCESS_SELF.format(
                allocated=_traffic(allocated_mb),
                remainder=_traffic(remainder),
            )
        )
        await send_config(bot, user.id, child, session)

    await call.answer()
    await activity.log_activity(
        session,
        user.id,
        "wallet_split",
        {
            "parent_id": service.id,
            "child_id": child.id,
            "allocated_mb": allocated_mb,
            "for_other": for_other,
            "recipient_id": recipient_id if for_other else None,
        },
    )


# ══════════════════════════════════════════════════════════════════
#  لغو از هر جایی
# ══════════════════════════════════════════════════════════════════

@router.callback_query(inline.WalletCB.filter(F.action == "cancel"))
async def cancel_wallet(
    call: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    await call.message.edit_text(MSG_CANCELLED)
    await call.answer()
