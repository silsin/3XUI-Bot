.PHONY: help backup-now backup-stats backup-cleanup backup-setup logs-bot logs-backup docker-up docker-down docker-logs

help:
	@echo "AlovpnBot - دستورات مدیریتی"
	@echo ""
	@echo "دستورات Docker:"
	@echo "  make docker-up      - شروع تمام سرویس‌ها"
	@echo "  make docker-down    - متوقف کردن تمام سرویس‌ها"
	@echo "  make docker-logs    - نمایش لاگ‌های تمام سرویس‌ها"
	@echo ""
	@echo "دستورات بک‌اپ:"
	@echo "  make backup-now     - اجرای بک‌اپ فوری"
	@echo "  make backup-stats   - نمایش آمار بک‌اپ‌ها"
	@echo "  make backup-cleanup - حذف بک‌اپ‌های قدیمی"
	@echo ""
	@echo "دستورات لاگ:"
	@echo "  make logs-bot       - لاگ‌های ربات"
	@echo "  make logs-backup    - لاگ‌های بک‌اپ"
	@echo ""

# Docker دستورات
docker-up:
	@echo "🚀 شروع سرویس‌ها..."
	docker-compose up -d
	@echo "✅ سرویس‌ها فعال شدند"

docker-down:
	@echo "🛑 متوقف کردن سرویس‌ها..."
	docker-compose down
	@echo "✅ سرویس‌ها متوقف شدند"

docker-logs:
	docker-compose logs -f

docker-restart:
	@echo "🔄 ری‌استارت سرویس‌ها..."
	docker-compose restart
	@echo "✅ سرویس‌ها ری‌استارت شدند"

# بک‌اپ دستورات
backup-now:
	@echo "💾 اجرای بک‌اپ فوری..."
	docker exec alovpn-backup /bin/sh /backup.sh now
	@echo "✅ بک‌اپ انجام شد"

backup-run:
	@echo "💾 اجرای بک‌اپ و پاکسازی..."
	docker exec alovpn-backup /bin/sh /backup.sh run
	@echo "✅ بک‌اپ انجام شد"

backup-stats:
	@echo "📊 آمار بک‌اپ‌ها:"
	docker exec alovpn-backup /bin/sh /backup.sh stats

backup-cleanup:
	@echo "🧹 حذف بک‌اپ‌های قدیمی..."
	docker exec alovpn-backup /bin/sh /backup.sh cleanup
	@echo "✅ پاکسازی انجام شد"

# لاگ دستورات
logs-bot:
	docker logs -f alovpn-bot

logs-backup:
	docker logs -f alovpn-backup

logs-all:
	docker-compose logs -f

# سرویس status
status:
	@echo "📋 وضعیت سرویس‌ها:"
	docker-compose ps

# تمیز‌کاری
clean:
	@echo "🧹 تمیز‌کاری کانتینرها..."
	docker-compose down -v
	@echo "✅ تمیز‌کاری انجام شد"

# بررسی سلامت
health:
	@echo "🏥 بررسی سلامت سرویس‌ها..."
	@echo ""
	@echo "وضعیت Docker:"
	docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	@echo ""
	@echo "آمار بک‌اپ:"
	@docker exec alovpn-backup /bin/sh /backup.sh stats 2>/dev/null || echo "❌ بک‌اپ سرویس در دسترس نیست"

