#!/bin/bash

# رنگ‌های خروجی
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# متغیرهای محیطی
BACKUP_DIR="${BACKUP_DIR:-/backups}"
DATA_DIR="${DATA_DIR:-/app/data}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
BACKUP_HOUR="${BACKUP_HOUR:-03}"
BACKUP_MINUTE="${BACKUP_MINUTE:-00}"

# ایجاد پوشه بک‌اپ
mkdir -p "$BACKUP_DIR"

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" >&2
}

warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# بک‌اپ فوری (بدون جدول‌بندی)
backup_now() {
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/bot_backup_$TIMESTAMP.db.gz"
    
    log "شروع بک‌اپ..."
    
    if [ ! -f "$DATA_DIR/bot.db" ]; then
        error "فایل دیتابیس یافت نشد: $DATA_DIR/bot.db"
        return 1
    fi
    
    # کپی دیتابیس و فشرده‌سازی
    if gzip -c "$DATA_DIR/bot.db" > "$BACKUP_FILE" 2>/dev/null; then
        SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        log "بک‌اپ موفقیت‌آمیز: $BACKUP_FILE ($SIZE)"
        
        # نمایش فایل
        ls -lh "$BACKUP_FILE"
        
        return 0
    else
        error "خرابی در ایجاد بک‌اپ"
        return 1
    fi
}

# حذف بک‌اپ‌های قدیمی
cleanup_old_backups() {
    log "پاکسازی بک‌اپ‌های قدیمی‌تر از $RETENTION_DAYS روز..."
    
    DELETED_COUNT=0
    while IFS= read -r old_file; do
        if [ -n "$old_file" ]; then
            log "حذف: $(basename "$old_file")"
            rm -f "$old_file"
            ((DELETED_COUNT++))
        fi
    done < <(find "$BACKUP_DIR" -name "bot_backup_*.db.gz" -mtime +$RETENTION_DAYS)
    
    if [ $DELETED_COUNT -gt 0 ]; then
        log "تعداد $DELETED_COUNT فایل قدیمی حذف شد"
    fi
}

# نمایش آمار بک‌اپ‌ها
show_stats() {
    log "آمار بک‌اپ‌ها:"
    echo ""
    if [ -d "$BACKUP_DIR" ]; then
        COUNT=$(find "$BACKUP_DIR" -name "bot_backup_*.db.gz" | wc -l)
        TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
        echo "تعداد بک‌اپ: $COUNT"
        echo "حجم کل: $TOTAL_SIZE"
        echo ""
        echo "آخرین بک‌اپ‌ها:"
        ls -lhtr "$BACKUP_DIR"/bot_backup_*.db.gz 2>/dev/null | tail -5
    else
        warning "پوشه بک‌اپ وجود ندارد"
    fi
}

# راه‌اندازی cron
setup_cron() {
    log "تنظیم جدول‌بندی cron..."
    
    CRON_ENTRY="$BACKUP_MINUTE $BACKUP_HOUR * * * /bin/sh /backup.sh run 2>&1 | logger"
    
    # اضافه کردن به crontab اگر موجود نیست
    (crontab -l 2>/dev/null | grep -q "/backup.sh run") || {
        (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
        log "cron تنظیم شد: ساعت $BACKUP_HOUR:$BACKUP_MINUTE هر روز"
    }
}

# نمایش راهنما
show_help() {
    cat << EOF
استفاده: $0 [دستور]

دستورات:
  run         - اجرای بک‌اپ فوری و پاکسازی
  now         - اجرای بک‌اپ فوری
  cleanup     - حذف بک‌اپ‌های قدیمی
  stats       - نمایش آمار بک‌اپ‌ها
  setup       - تنظیم جدول‌بندی cron
  help        - نمایش این راهنما

مثال:
  $0 run              # بک‌اپ و پاکسازی
  $0 stats            # نمایش آمار
  $0 cleanup          # حذف فایل‌های قدیمی

EOF
}

# اجرای دستور
case "${1:-run}" in
    run)
        backup_now && cleanup_old_backups
        ;;
    now)
        backup_now
        ;;
    cleanup)
        cleanup_old_backups
        ;;
    stats)
        show_stats
        ;;
    setup)
        setup_cron
        ;;
    help)
        show_help
        ;;
    *)
        error "دستور نامعلوم: $1"
        show_help
        exit 1
        ;;
esac

exit 0
