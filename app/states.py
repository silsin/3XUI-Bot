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
    # مراحل مدیریت کیف پول
    wallet_search = State()
    wallet_set_balance = State()
    wallet_bonus_user = State()
    wallet_bonus_amount = State()
    wallet_bonus_reason = State()
    channel_name = State()
    channel_id = State()
    # مراحل ساخت پنل جدید
    panel_title = State()
    panel_variant = State()
    panel_url = State()
    panel_path = State()
    panel_token = State()
    panel_user = State()
    panel_pass = State()
    panel_host = State()
    # ویرایش فیلد پنل
    panel_field = State()
    # مراحل ساخت اینباند جدید
    inbound_protocol = State()
    inbound_port = State()
    inbound_remark = State()
    inbound_network = State()
    inbound_security = State()
    inbound_extra = State()
    # مراحل انتقال ربات به سرور جدید
    transfer_creds = State()
    transfer_confirm = State()


class WalletTopupFlow(StatesGroup):
    """جریان درخواست شارژ کیف پول."""
    waiting_amount = State()       # کاربر مبلغ را انتخاب یا تایپ می‌کند
    waiting_receipt = State()      # کاربر رسید را ارسال می‌کند


class WalletFlow(StatesGroup):
    # ── مرحله ۱: انتخاب سرویس والد (از طریق inline keyboard)
    # (بدون state — مستقیم با callback شروع می‌شود)

    # ── مرحله ۲: ورود حجم (برای خودم یا انتقال)
    entering_size = State()        # کاربر حجم را تایپ می‌کند

    # ── مرحله ۳ (انتقال): ورود آیدی تلگرام گیرنده
    entering_recipient = State()   # کاربر آیدی عددی تلگرام گیرنده را تایپ می‌کند

    # ── مرحله ۴: تأیید نهایی (inline keyboard)
    confirming = State()           # نمایش خلاصه و دکمه تأیید/لغو


class ActivitySearch(StatesGroup):
    waiting_user_id = State()
