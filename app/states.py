from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    waiting_receipt = State()
    waiting_promo_code = State()  # کاربر در حال وارد کردن کد تخفیف است


class AdminFlow(StatesGroup):
    editing_setting = State()
    editing_image = State()
    duration_title = State()
    duration_days = State()
    package_field = State()
    reject_note = State()
    broadcast = State()
    user_lookup = State()
    gift_days = State()
    # مراحل ساخت تخفیف جدید
    offer_title = State()
    offer_type = State()
    offer_value = State()
    offer_code = State()
    offer_max_uses = State()
    offer_per_user = State()
    offer_valid_days = State()


class WalletFlow(StatesGroup):
    """جریان تقسیم سرویس — تمام‌چیز در یک state با inline keyboards."""
    confirming = State()  # نمایش خلاصه و دکمه‌های تأیید


class ActivitySearch(StatesGroup):
    waiting_user_id = State()
