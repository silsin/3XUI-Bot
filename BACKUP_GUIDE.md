# 📦 راهنمای سیستم بک‌اپ خودکار

## نمای کلی

سیستم بک‌اپ خودکار AlovpnBot به صورت یک سرویس Docker جداگانه اجرا می‌شود که هر روز به‌صورت تعیین‌شده یک بک‌اپ از دیتابیس می‌گیرد.

## 🚀 شروع کار

### 1. راه‌اندازی

بک‌اپ به‌صورت خودکار در فایل `docker-compose.yml` تعریف شده است. کافی است docker-compose را شروع کنید:

```bash
docker-compose up -d
```

این دستور دو سرویس را شروع می‌کند:
- **bot**: ربات اصلی
- **backup**: سرویس بک‌اپ خودکار

### 2. تعریف زمان بک‌اپ

زمان بک‌اپ را در فایل `.env` تعیین کنید:

```bash
# فایل .env

# ساعت اجرای بک‌اپ (صفر تا 23)
BACKUP_HOUR=03

# دقیقه اجرای بک‌اپ (صفر تا 59)
BACKUP_MINUTE=00

# تعداد روزهایی که بک‌اپ نگهداری شود (پیش‌فرض: 30 روز)
BACKUP_RETENTION_DAYS=30
```

**مثال:** ساعت `03:00` (3 صبح) هر روز بک‌اپ می‌گیرد.

---

## 📋 دستورات مدیریتی

اسکریپت بک‌اپ را می‌توانید به صورت دستی نیز اجرا کنید:

### بک‌اپ فوری

```bash
docker exec alovpn-backup /bin/sh /backup.sh now
```

### اجرای بک‌اپ و پاکسازی

```bash
docker exec alovpn-backup /bin/sh /backup.sh run
```

### نمایش آمار بک‌اپ‌ها

```bash
docker exec alovpn-backup /bin/sh /backup.sh stats
```

### حذف بک‌اپ‌های قدیمی

```bash
docker exec alovpn-backup /bin/sh /backup.sh cleanup
```

### نمایش راهنما

```bash
docker exec alovpn-backup /bin/sh /backup.sh help
```

---

## 📂 مسیر ذخیره بک‌اپ‌ها

تمام بک‌اپ‌ها در پوشه `./backups` (کنار `docker-compose.yml`) ذخیره می‌شوند:

```
./backups/
├── bot_backup_20260914_120000.db.gz
├── bot_backup_20260915_030000.db.gz
└── bot_backup_20260916_030000.db.gz
```

**نام‌گذاری:** `bot_backup_YYYYMMDD_HHMMSS.db.gz`

---

## 🔄 بازیابی بک‌اپ

### روش 1: توقف و جایگزین (بدون داده جدید)

```bash
# سرویس ربات را متوقف کنید
docker stop alovpn-bot

# بک‌اپ را داخل کانتینر کپی کنید
docker cp ./backups/bot_backup_20260914_120000.db.gz alovpn-bot:/tmp/
docker exec alovpn-bot gunzip /tmp/bot_backup_20260914_120000.db.gz
docker exec alovpn-bot cp /tmp/bot_backup_20260914_120000.db /app/data/bot.db

# ربات را دوباره شروع کنید
docker start alovpn-bot
```

### روش 2: درون‌پذیری شامل تاریخ بالاتر (نسخه‌برداری در پس‌زمینه)

```bash
# پوشه پشتیبان جدید برای نسخه فعلی
mkdir -p ./backups/current
docker cp alovpn-bot:/app/data/bot.db ./backups/current/bot_$(date +%Y%m%d_%H%M%S).db

# بک‌اپ را جایگزین کنید
docker cp ./backups/bot_backup_20260914_120000.db.gz alovpn-bot:/tmp/
docker exec alovpn-bot sh -c 'gunzip /tmp/bot_backup_*.db.gz && cp /tmp/bot_backup_*.db /app/data/bot.db'

# دوباره شروع کنید
docker restart alovpn-bot
```

---

## 📊 نمایش حجم بک‌اپ‌ها

```bash
# حجم کل
du -sh ./backups

# تفصیلی
ls -lh ./backups/bot_backup_*.db.gz
```

---

## ⚙️ تنظیمات پیشرفته

### تغییر مسیر ذخیره بک‌اپ

ویرایش `docker-compose.yml`:

```yaml
backup:
  volumes:
    # ولوم دیتابیس
    - bot_data:/app/data:ro
    # مسیر ذخیره جدید (مثلاً دایرکتوری اضافی)
    - /mnt/external-drive/backups:/backups
```

### فشرده‌سازی بیشتر

برای کاهش حجم فایل:

```bash
# gzip بجای bzip2
# ویرایش backup.sh:
# bzip2 -c "$DATA_DIR/bot.db" > "$BACKUP_FILE.bz2"
```

### ارسال بک‌اپ به محل دور

```bash
# افزودن به پایان backup.sh:
# scp -r "$BACKUP_DIR/bot_backup_*.db.gz" remote@example.com:/backups/
```

---

## 🛡️ نکات ایمنی

✅ **بک‌اپ‌ها فشرده‌سازی شده‌اند** (gzip) برای صرفه‌جویی در فضا

✅ **فایل‌های قدیمی به‌صورت خودکار حذف می‌شوند** (پیش‌فرض 30 روز)

✅ **خطای‌های بک‌اپ در لاگ‌ها نوشته می‌شوند**

❌ **توجه:** بک‌اپ‌ها محلی هستند. برای ایمنی بیشتر:
- بک‌اپ‌ها را به سرور دور منتقل کنید
- رمزگذاری کنید
- تکثیر کنید

---

## 🔍 حل‌المسائل

### بک‌اپ اجرا نمی‌شود

```bash
# بررسی لاگ‌های backup container
docker logs alovpn-backup

# بررسی cron
docker exec alovpn-backup crontab -l
```

### فضای دیسک کم است

```bash
# حذف دستی بک‌اپ‌های قدیمی
docker exec alovpn-backup /bin/sh /backup.sh cleanup

# یا تقلیل BACKUP_RETENTION_DAYS
```

### بازیابی شکست خورد

```bash
# بررسی دیتابیس
docker exec alovpn-bot sqlite3 /app/data/bot.db "SELECT COUNT(*) FROM sqlite_master;"

# اگر손상 شده، دیتابیسی دیگر از بک‌اپ استفاده کنید
```

---

## 📞 پشتیبانی

برای سوالات، مسائل بک‌اپ را در لاگ‌های Docker بررسی کنید:

```bash
docker logs -f alovpn-backup
```

