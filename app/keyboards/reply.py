from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.texts import MAIN_BUTTONS

ADMIN_BUTTON = "🛠 پنل مدیریت"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """کیبورد پایین اصلی."""
    builder = ReplyKeyboardBuilder()
    for row in MAIN_BUTTONS:
        builder.row(*(KeyboardButton(text=text) for text in row))
    if is_admin:
        builder.row(KeyboardButton(text=ADMIN_BUTTON))
    # is_persistent عمداً تنظیم نمی‌شود؛ کیبورد پایدار روی اندروید دکمه بازگشت
    # فیزیکی را می‌بلعد. حالت پیش‌فرض اجازه می‌دهد کاربر کیبورد را ببندد.
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="یک گزینه را انتخاب کنید...",
    )


def remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
