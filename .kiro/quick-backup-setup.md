# 🚀 راه‌اندازی سریع بک‌اپ اتوماتیک

## ✅ انجام شد

سیستم بک‌اپ اتوماتیک آماده است. فایل‌های زیر اضافه شده:

- ✅ `docker-compose.yml` - سرویس بک‌اپ اضافه شده
- ✅ `scripts/backup.sh` - اسکریپت بک‌اپ اصلی
- ✅ `backup.ps1` - ابزار بک‌اپ برای Windows
- ✅ `Makefile` - دستورات مدیریتی
- ✅ `BACKUP_GUIDE.md` - راهنمای کامل

---

## 🎯 شروع سریع (3 مرحله)

### 1️⃣ تنظیم `.env` (اختیاری)

```bash
# فایل .env

# زمان بک‌اپ (ساعت 3 صبح)
BACKUP_HOUR=03
BACKUP_MINUTE=00

# حفظ بک‌اپ برای 30 روز
BACKUP_RETENTION_DAYS=30
```

### 2️⃣ شروع Docker

```bash
docker-compose up -d
```

بس! سرویس بک‌اپ فعال است.

### 3️⃣ بررسی

```bash
docker ps
# باید دو سرویس دید: alovpn-bot و alovpn-backup
```

---

## 📱 دستورات سریع

### Windows (PowerShell)
```powershell
.\backup.ps1 now       # بک‌اپ فوری
.\backup.ps1 stats     # نمایش آمار
```

### Linux/Mac (Bash)
```bash
docker exec alovpn-backup /bin/sh /backup.sh now      # بک‌اپ فوری
docker exec alovpn-backup /bin/sh /backup.sh stats    # آمار
```

### Makefile
```bash
make backup-now        # بک‌اپ فوری
make backup-stats      # نمایش آمار
make backup-cleanup    # حذف قدیمی‌ها
```

---

## 🎯 تنظیمات پیش‌فرض

| تنظیم | مقدار | توضیح |
|------|-------|------|
| **زمان بک‌اپ** | 03:00 | هر روز ساعت 3 صبح |
| **حفظ برای** | 30 روز | بک‌اپ‌های قدیمی‌تر حذف می‌شوند |
| **مسیر بک‌اپ** | `./backups/` | کنار `docker-compose.yml` |
| **فشرده‌سازی** | gzip | کاهش 70-80% حجم |

---

## 📂 ساختار پوشه

```
alovpnBot/
├── docker-compose.yml        (✏️ بک‌اپ سرویس اضافه شده)
├── scripts/
│   ├── backup.sh            (✨ جدید)
│   └── Dockerfile.backup    (✨ جدید)
├── backups/                 (✨ جدید - بک‌اپ‌ها اینجا)
│   ├── bot_backup_20260914_030000.db.gz
│   └── ...
├── backup.ps1              (✨ جدید - Windows)
├── Makefile                (✨ جدید)
└── BACKUP_GUIDE.md         (✨ جدید - راهنمای کامل)
```

---

## 🔍 بررسی وضعیت

### لاگ‌های بک‌اپ
```bash
docker logs -f alovpn-backup
```

### لیست بک‌اپ‌ها
```bash
ls -lh ./backups/
```

### حجم کل
```bash
du -sh ./backups/
```

---

## ⚠️ مهم

1. **بک‌اپ‌ها محلی هستند** - برای ایمنی بیشتر به محل دور منتقل کنید
2. **فضای دیسک** - مطمئن شوید حداقل 1 GB فضای خالی دارید
3. **جدول‌بندی** - شامل شامل شامل بک‌اپ فقط هنگام اجرا است

---

## 📞 مشاوره

- **خطا در بک‌اپ؟** → `docker logs alovpn-backup`
- **بک‌اپ تاخیر دارد؟** → `docker ps` (وضعیت سرویس‌ها)
- **حجم بیشتر است؟** → `BACKUP_RETENTION_DAYS` را کاهش دهید

---

## ✨ نکات اضافی

- **بک‌اپ جدید شده؟** → `make backup-stats` (فوری‌ترین راه)
- **فضای دیسک کم؟** → `make backup-cleanup` (حذف قدیمی‌ها)
- **راه‌اندازی مجدد؟** → `docker-compose restart`

**همه چیز آماده است!** 🎉

