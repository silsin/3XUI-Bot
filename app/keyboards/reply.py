from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.texts import (
    BTN_BUY,
    BTN_GUIDE,
    BTN_INVITE,
    BTN_MY_SERVICES,
    BTN_MY_WALLET,
    BTN_POINTS,
    BTN_RENEW,
    BTN_SUPPORT,
    BTN_TRIAL,
    MAIN_BUTTONS,
)

ADMIN_BUTTON = "🛠 پنل مدیریت"

# رنگ دکمه‌ها (Bot API 9.4). کلاینت‌های قدیمی این را نادیده می‌گیرند.
# primary=آبی، success=سبز، danger=قرمز
_BTN_STYLE: dict[str, str] = {
    BTN_TRIAL: "primary",
    BTN_BUY: "success",
    BTN_RENEW: "primary",
    BTN_MY_SERVICES: "primary",
    BTN_POINTS: "primary",
    BTN_GUIDE: "primary",
    BTN_INVITE: "danger",
    BTN_SUPPORT: "danger",
    BTN_MY_WALLET: "success",
    ADMIN_BUTTON: "danger",
}


def _btn(text: str) -> KeyboardButton:
    return KeyboardButton(text=text, style=_BTN_STYLE.get(text))


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """کیبورد پایین اصلی با دکمه‌های رنگی."""
    builder = ReplyKeyboardBuilder()
    for row in MAIN_BUTTONS:
        builder.row(*(_btn(text) for text in row))
    if is_admin:
        builder.row(_btn(ADMIN_BUTTON))
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="یک گزینه را انتخاب کنید...",
    )


def remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
