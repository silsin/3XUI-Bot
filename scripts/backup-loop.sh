#!/bin/sh

# اسکریپت حلقه بک‌اپ - بجای cron
# ساعت و دقیقه را از متغیرهای محیطی بخوانید

BACKUP_HOUR="${BACKUP_HOUR:-03}"
BACKUP_MINUTE="${BACKUP_MINUTE:-00}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

log "شروع سرویس بک‌اپ خودکار"
log "زمان اجرا: $BACKUP_HOUR:$BACKUP_MINUTE هر روز"
log "حفظ بک‌اپ برای: $BACKUP_RETENTION_DAYS روز"

# حلقه بی‌نهایت
while true; do
    CURRENT_HOUR=$(date +%H)
    CURRENT_MINUTE=$(date +%M)
    CURRENT_SECOND=$(date +%S)
    
    # اگر ساعت و دقیقه مطابقت دارند، بک‌اپ اجرا شود
    if [ "$CURRENT_HOUR" = "$BACKUP_HOUR" ] && [ "$CURRENT_MINUTE" = "$BACKUP_MINUTE" ]; then
        log "⏰ زمان بک‌اپ رسید!"
        
        # اجرای بک‌اپ
        /bin/sh /backup.sh run
        
        # صبر کنید 61 ثانیه تا دوباره تکرار نشود
        log "صبر 61 ثانیه تا دوباره اجرا نشود..."
        sleep 61
    fi
    
    # هر 30 ثانیه بررسی کنید
    sleep 30
done

