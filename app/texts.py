"""متن‌های ثابت و مقادیر پیش‌فرض تنظیمات قابل ویرایش توسط ادمین."""

from __future__ import annotations

# ---------- دکمه‌های کیبورد پایین ----------
BTN_TRIAL = "تست رایگان"
BTN_BUY = "خرید اشتراک"
BTN_RENEW = "تمدید سرویس"
BTN_MY_SERVICES = "سرویس های من"
BTN_POINTS = "امتیاز من"
BTN_GUIDE = "آموزش استفاده"
BTN_INVITE = "دعوت از دوستان"
BTN_SUPPORT = "پشتیبانی"
BTN_MY_WALLET = "💾 کیف داده"

MAIN_BUTTONS = [
    [BTN_TRIAL, BTN_BUY],
    [BTN_RENEW, BTN_MY_SERVICES],
    [BTN_POINTS, BTN_GUIDE],
    [BTN_INVITE, BTN_SUPPORT],
]

# ---------- کلیدهای تنظیمات ----------
S_WELCOME_TEXT = "welcome_text"
S_WELCOME_IMAGE = "welcome_image"
S_GUIDE_TEXT = "guide_text"
S_SUPPORT_TEXT = "support_text"
S_BUY_INSTRUCTION = "buy_instruction"
S_CARD_NUMBER = "card_number"
S_CARD_HOLDER = "card_holder"
S_INVITE_TEXT = "invite_text"
S_POINTS_TEXT = "points_text"
S_TRIAL_ENABLED = "trial_enabled"
S_TRIAL_DAYS = "trial_days"
S_TRIAL_MB = "trial_mb"
S_TRIAL_INBOUND = "trial_inbound_id"
S_REFERRAL_POINTS = "referral_points"
S_POINTS_PER_DAY = "points_per_day"
S_REDEEM_INBOUND = "redeem_inbound_id"
S_REDEEM_MIN_DAYS = "redeem_min_days"
S_CONFIG_CAPTION = "config_caption"
# فهرست inboundهای چند-پروتکل (با کاما). خالی = استفاده از inbound پکیج/تنظیمات
S_MULTI_INBOUNDS = "multi_inbounds"

DEFAULT_SETTINGS: dict[str, str] = {
    S_WELCOME_TEXT: (
        "🌟 <b>به ربات فروش اشتراک خوش آمدید</b>\n\n"
        "سلام {name} عزیز 👋\n"
        "از این ربات می‌توانید:\n"
        "• 🎁 اشتراک تست رایگان دریافت کنید\n"
        "• 🛒 اشتراک بخرید و آنی کانفیگ بگیرید\n"
        "• ♻️ سرویس فعلی خود را تمدید کنید\n"
        "• 📊 حجم و روزهای باقی‌مانده را ببینید\n"
        "• 👥 با دعوت دوستان امتیاز بگیرید و اشتراک هدیه بگیرید\n\n"
        "برای شروع یکی از گزینه‌های پایین را انتخاب کنید 👇"
    ),
    S_WELCOME_IMAGE: "",
    S_GUIDE_TEXT: (
        "📚 <b>آموزش اتصال</b>\n\n"
        "<b>اندروید:</b> نرم‌افزار <b>v2rayNG</b> را نصب کنید، روی ➕ بزنید و "
        "«Import from clipboard» را انتخاب کنید.\n\n"
        "<b>آیفون:</b> نرم‌افزار <b>Streisand</b> یا <b>V2Box</b> را نصب کنید و "
        "کانفیگ را از کلیپ‌بورد اضافه کنید.\n\n"
        "<b>ویندوز:</b> نرم‌افزار <b>v2rayN</b> را نصب کنید و با "
        "Ctrl+V کانفیگ را اضافه کنید.\n\n"
        "در صورت بروز مشکل با پشتیبانی در تماس باشید."
    ),
    S_SUPPORT_TEXT: (
        "☎️ <b>پشتیبانی</b>\n\n"
        "پاسخگویی هر روز از ساعت ۹ تا ۲۴\n"
        "آیدی پشتیبانی: @YourSupportID"
    ),
    S_BUY_INSTRUCTION: (
        "💳 <b>پرداخت</b>\n\n"
        "لطفاً مبلغ <b>{amount}</b> تومان را به کارت زیر واریز کنید و سپس "
        "تصویر رسید را ارسال نمایید.\n\n"
        "شماره کارت:\n<code>{card_number}</code>\n"
        "به نام: <b>{card_holder}</b>\n\n"
        "⚠️ پس از واریز، روی دکمه «ارسال رسید» بزنید و عکس فیش را بفرستید.\n"
        "سفارش شما حداکثر تا ۳۰ دقیقه بررسی و کانفیگ ارسال می‌شود."
    ),
    S_CARD_NUMBER: "6037-9999-9999-9999",
    S_CARD_HOLDER: "نام صاحب حساب",
    S_INVITE_TEXT: (
        "👥 <b>دعوت از دوستان</b>\n\n"
        "با لینک اختصاصی زیر دوستان خود را دعوت کنید.\n"
        "به ازای <b>هر دعوت موفق</b> (اولین خرید دوست شما) "
        "<b>{points}</b> امتیاز می‌گیرید.\n"
        "امتیازها را می‌توانید به <b>روز اشتراک هدیه</b> تبدیل کنید.\n\n"
        "🔗 لینک شما:\n{link}\n\n"
        "تعداد دعوت‌های موفق شما: <b>{invited}</b> نفر"
    ),
    S_POINTS_TEXT: (
        "🏅 <b>امتیاز من</b>\n\n"
        "امتیاز فعلی: <b>{points}</b>\n"
        "نرخ تبدیل: هر <b>{per_day}</b> امتیاز = <b>۱ روز</b> اشتراک هدیه\n"
        "معادل: <b>{days}</b> روز\n\n"
        "برای دریافت امتیاز از بخش «دعوت از دوستان» استفاده کنید."
    ),
    S_TRIAL_ENABLED: "1",
    S_TRIAL_DAYS: "1",
    S_TRIAL_MB: "1024",
    S_TRIAL_INBOUND: "4",
    S_REFERRAL_POINTS: "10",
    S_POINTS_PER_DAY: "10",
    S_REDEEM_INBOUND: "4",
    S_REDEEM_MIN_DAYS: "1",
    S_MULTI_INBOUNDS: "4",
    S_CONFIG_CAPTION: (
        "✅ <b>سرویس شما آماده است</b>\n\n"
        "{title}\n"
        "⏳ اعتبار: <b>{days}</b> روز\n"
        "📦 حجم: <b>{traffic}</b>\n\n"
        "کانفیگ را کپی کرده و در نرم‌افزار خود اضافه کنید:\n"
        "<code>{link}</code>\n\n"
        "برای راهنمای اتصال از «آموزش استفاده» استفاده کنید."
    ),
}

# ---------- پیام‌های ثابت ----------
MSG_UNKNOWN = "متوجه نشدم 🤔 لطفاً از دکمه‌های پایین استفاده کنید."
MSG_BLOCKED = "⛔️ دسترسی شما به ربات محدود شده است."
MSG_ERROR = "❌ خطایی رخ داد. لطفاً بعداً تلاش کنید یا به پشتیبانی پیام دهید."
MSG_PANEL_ERROR = (
    "❌ در ساخت کانفیگ خطایی رخ داد. مبلغ شما محفوظ است و "
    "پشتیبانی در اسرع وقت پیگیری می‌کند."
)

MSG_TRIAL_DISABLED = "🚫 تست رایگان در حال حاضر غیرفعال است."
MSG_TRIAL_ALREADY = (
    "⚠️ شما قبلاً تست رایگان خود را دریافت کرده‌اید.\n"
    "برای ادامه استفاده می‌توانید از «خرید اشتراک» استفاده کنید."
)
MSG_TRIAL_WAIT = "⏳ در حال ساخت کانفیگ تست..."

MSG_CHOOSE_DURATION = "⏱ <b>مدت زمان اشتراک</b> را انتخاب کنید:"
MSG_NO_DURATION = "😔 در حال حاضر پلنی برای فروش موجود نیست."
MSG_CHOOSE_PACKAGE = "📦 یکی از <b>پکیج‌های {duration}</b> را انتخاب کنید:"
MSG_NO_PACKAGE = "😔 برای این مدت زمان پکیجی موجود نیست."

MSG_NO_SERVICES = (
    "شما هنوز سرویس فعالی ندارید.\nبا «خرید اشتراک» اولین سرویس خود را بگیرید 🛒"
)
MSG_RECEIPT_ASK = (
    "📸 لطفاً <b>تصویر رسید پرداخت</b> را ارسال کنید.\n"
    "می‌توانید عکس یا فایل بفرستید. برای انصراف /cancel را بزنید."
)
MSG_RECEIPT_INVALID = "لطفاً یک <b>عکس</b> یا <b>فایل</b> رسید ارسال کنید."
MSG_RECEIPT_SENT = (
    "✅ رسید شما دریافت شد و برای بررسی به پشتیبانی ارسال گردید.\n"
    "به‌محض تأیید، کانفیگ به‌صورت خودکار برای شما ارسال می‌شود. 🙏"
)
MSG_ORDER_REJECTED = (
    "❌ متأسفانه رسید سفارش <b>#{order_id}</b> تأیید نشد.\n{note}\n"
    "در صورت نیاز با پشتیبانی در تماس باشید."
)
MSG_CANCELLED = "لغو شد."

# ---------- پیام‌های سیستم تخفیف ----------
MSG_PROMO_ASK = (
    "🏷 <b>کد تخفیف</b>\n\n"
    "کد تخفیف خود را وارد کنید:\n"
    "(برای انصراف /cancel بزنید)"
)
MSG_PROMO_APPLIED = "✅ کد تخفیف <b>{code}</b> اعمال شد!\n{summary}"
MSG_PROMO_REMOVED = "تخفیف حذف شد."
MSG_PROMO_INVALID = "❌ {error}"

# ---------- دکمه‌های اینلاین ----------
BTN_BACK = "🔙 بازگشت"
BTN_CANCEL = "✖️ انصراف"
BTN_CONFIRM_BUY = "✅ تأیید و پرداخت"
BTN_SEND_RECEIPT = "📸 ارسال رسید"
BTN_APPROVE = "✅ تأیید"
BTN_REJECT = "❌ رد"
BTN_ENTER_PROMO = "🏷 دارم کد تخفیف"
BTN_REMOVE_PROMO = "✖️ حذف تخفیف"

# ---------- کیف داده (split & transfer) — ساده‌شده ----------
BTN_SPLIT_SERVICE = "💾 تقسیم این کانفیگ"
BTN_SPLIT_FOR_SELF = "➕ برای خودم"
BTN_SPLIT_FOR_OTHER = "🔁 برای کاربر دیگر"
BTN_CONFIRM_SPLIT = "✅ تأیید و ساخت"
BTN_SIZE_1GB  = "1️⃣ 1 GB"
BTN_SIZE_2GB  = "2️⃣ 2 GB"
BTN_SIZE_5GB  = "5️⃣ 5 GB"
BTN_SIZE_10GB = "🔟 10 GB"
BTN_SIZE_20GB = "2️⃣0️⃣ 20 GB"

MSG_WALLET_INTRO = (
    "💾 <b>تقسیم کانفیگ</b>\n\n"
    "برای این کانفیگ حجمی جدا کنید:\n"
    "• <b>برای خودم:</b> یک کانفیگ جدید برای خود ایجاد کنید\n"
    "• <b>برای دیگری:</b> یک کانفیگ برای کاربر دیگری بسازید\n\n"
    "کانفیگ جدید همان تاریخ انقضا را خواهد داشت."
)
MSG_WALLET_NO_SERVICE = (
    "⚠️ <b>سرویس قابل تقسیم ندارید.</b>\n\n"
    "برای تقسیم، سرویس باید:\n"
    "• فعال و دارای حجم مشخص باشد\n"
    "• حداقل ۱۰۰ مگابایت موجودی آزاد داشته باشد\n"
    "• منقضی نشده باشد"
)
MSG_WALLET_SELECT_TYPE = (
    "📋 <b>سرویس انتخابی:</b> {title}\n"
    "📊 موجودی آزاد: <b>{available}</b>\n"
    "⏳ انقضا: <b>{expires}</b>\n\n"
    "حجمی را انتخاب کنید:"
)
MSG_WALLET_CONFIRM_SELF = (
    "✅ <b>تأیید ساخت کانفیگ</b>\n\n"
    "📋 سرویس اصلی: <b>{parent_title}</b>\n"
    "📊 حجم جدا‌شده: <b>{allocated}</b>\n"
    "📊 باقی‌مانده: <b>{remainder}</b>\n"
    "⏳ انقضا: <b>{expires}</b>\n\n"
    "آیا تأیید می‌کنید؟"
)
MSG_WALLET_CONFIRM_OTHER = (
    "✅ <b>تأیید انتقال کانفیگ</b>\n\n"
    "📋 سرویس اصلی: <b>{parent_title}</b>\n"
    "📊 حجم جدا‌شده: <b>{allocated}</b>\n"
    "📊 باقی‌مانده: <b>{remainder}</b>\n"
    "⏳ انقضا: <b>{expires}</b>\n"
    "👤 گیرنده: <b>{recipient_name}</b>\n\n"
    "آیا تأیید می‌کنید؟"
)
MSG_WALLET_PROCESSING = "⏳ در حال ساخت کانفیگ..."
MSG_WALLET_SUCCESS_SELF = (
    "🎉 <b>کانفیگ جدید ساخته شد!</b>\n\n"
    "📊 حجم: <b>{allocated}</b>\n"
    "📊 موجودی باقی‌مانده سرویس اصلی: <b>{remainder}</b>"
)
MSG_WALLET_SUCCESS_OTHER = (
    "🎉 <b>کانفیگ با موفقیت ساخته و ارسال شد!</b>\n\n"
    "📊 حجم: <b>{allocated}</b>\n"
    "👤 گیرنده: <b>{recipient_name}</b>\n"
    "📊 موجودی باقی‌مانده سرویس اصلی: <b>{remainder}</b>"
)
MSG_WALLET_RECIPIENT_NOT_FOUND = (
    "❌ کاربری با این نام‌کاربری پیدا نشد.\n"
    "لطفاً بررسی کنید و دوباره سعی کنید.\n"
    "مثال: john یا @john"
)
