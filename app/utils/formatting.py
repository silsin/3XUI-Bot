"""کمک‌تابع‌های نمایش: اعداد فارسی، تاریخ شمسی، حجم و قیمت."""

from __future__ import annotations

from datetime import datetime, timezone

GB = 1024 ** 3
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

_JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)


def fa_digits(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


def money(amount: int) -> str:
    """۱۲۳٬۰۰۰ تومان"""
    return fa_digits(f"{int(amount):,}").replace(",", "٬")


def toman_short(amount: int) -> str:
    """نمایش خوانا: ۲۰۰ هزار تومان / ۲ میلیون تومان / ۲۵٬۵۰۰ تومان"""
    amount = int(amount)
    if amount <= 0:
        return "۰ تومان"
    if amount % 1_000_000 == 0:
        return f"{fa_digits(amount // 1_000_000)} میلیون تومان"
    if amount % 1000 == 0:
        return f"{fa_digits(amount // 1000)} هزار تومان"
    return f"{money(amount)} تومان"


def traffic(mb: int) -> str:
    """حجم بر حسب مگابایت؛ زیر ۱ گیگ مگابایت، بالاتر گیگابایت. ۰ = نامحدود."""
    if mb <= 0:
        return "نامحدود"
    if mb < 1024:
        return f"{fa_digits(mb)} مگابایت"
    gb = mb / 1024
    text = str(int(gb)) if gb == int(gb) else f"{gb:.1f}".rstrip("0").rstrip(".")
    return f"{fa_digits(text)} گیگابایت"


def human_bytes(size: int) -> str:
    if size <= 0:
        return "۰"
    units = ("بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت")
    idx = 0
    value = float(size)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    text = f"{value:.0f}" if value >= 10 or idx == 0 else f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{fa_digits(text)} {units[idx]}"


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد بدون وابستگی)."""
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = (
        365 * gy2
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + g_d_m[gm2]
        + gd2
    )
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    for i, days in enumerate((31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)):
        if j_day_no < days:
            return jy, i + 1, j_day_no + 1
        j_day_no -= days
    return jy, 12, j_day_no + 1


def jalali_date(value: datetime | None) -> str:
    if value is None:
        return "نامحدود"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    jy, jm, jd = gregorian_to_jalali(value.year, value.month, value.day)
    return f"{fa_digits(jd)} {_JALALI_MONTHS[jm - 1]} {fa_digits(jy)}"


def days_left(expires_at: datetime | None) -> int:
    """روزهای باقی‌مانده (رو به بالا). -1 یعنی نامحدود، 0 یعنی منقضی."""
    if expires_at is None:
        return -1
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return 0
    return max(1, -(-int(seconds) // 86400))


def days_left_text(expires_at: datetime | None) -> str:
    if expires_at is None:
        return "نامحدود"
    remaining = days_left(expires_at)
    return "منقضی شده" if remaining <= 0 else f"{fa_digits(remaining)} روز"


def usage_text(used: int, total: int) -> str:
    if total <= 0:
        return f"{human_bytes(used)} از نامحدود"
    remaining = max(0, total - used)
    percent = min(100, int(used / total * 100)) if total else 0
    return (
        f"{human_bytes(used)} از {human_bytes(total)} "
        f"({fa_digits(percent)}٪) — باقی‌مانده {human_bytes(remaining)}"
    )
