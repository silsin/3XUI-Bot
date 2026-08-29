from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    marker = "sqlite+aiosqlite:///"
    if url.startswith(marker):
        raw = url[len(marker) :]
        path = Path(raw.lstrip("/") if raw.startswith("//") else raw)
        path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        _ensure_sqlite_dir(url)
        _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


def _migrate_gb_to_mb(conn) -> None:
    """مهاجرت ستون traffic_gb (گیگ) به traffic_mb (مگابایت) در دیتابیس موجود."""
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    for table in ("packages", "orders", "services"):
        if table not in tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "traffic_gb" not in cols:
            continue
        if "traffic_mb" not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN traffic_mb INTEGER DEFAULT 0"))
            conn.execute(text(f"UPDATE {table} SET traffic_mb = traffic_gb * 1024"))
        else:
            # پرکردن مقادیری که در مهاجرت ناقص قبلی صفر مانده‌اند
            conn.execute(
                text(f"UPDATE {table} SET traffic_mb = traffic_gb * 1024 "
                     "WHERE traffic_mb = 0 AND traffic_gb > 0")
            )
        # حذف ستون قدیمی traffic_gb (NOT NULL) تا insert جدید نشکند
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN traffic_gb"))
    # ستون notify_msgs برای پیگیری پیام رسید همه ادمین‌ها
    if "orders" in tables:
        ocols = {c["name"] for c in inspector.get_columns("orders")}
        if "notify_msgs" not in ocols:
            conn.execute(text("ALTER TABLE orders ADD COLUMN notify_msgs TEXT DEFAULT ''"))
    # مهاجرت کلید تنظیمات trial_gb -> trial_mb
    if "settings" in tables:
        row = conn.execute(
            text("SELECT value FROM settings WHERE key='trial_gb'")
        ).fetchone()
        if row is not None:
            exists = conn.execute(
                text("SELECT 1 FROM settings WHERE key='trial_mb'")
            ).fetchone()
            if exists is None:
                try:
                    mb = int(str(row[0]).strip()) * 1024
                except (TypeError, ValueError):
                    mb = 1024
                conn.execute(
                    text(
                        "INSERT INTO settings (key, value, updated_at) "
                        "VALUES ('trial_mb', :v, CURRENT_TIMESTAMP)"
                    ),
                    {"v": str(mb)},
                )


def _backfill_service_clients(conn) -> None:
    """برای سرویس‌های قدیمی (تک‌کانفیگ) یک ردیف service_clients می‌سازد."""
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if "services" not in tables or "service_clients" not in tables:
        return
    rows = conn.execute(
        text(
            "SELECT s.id, s.inbound_id, s.client_uuid, s.email, s.config_link, "
            "s.used_bytes FROM services s "
            "WHERE NOT EXISTS (SELECT 1 FROM service_clients c WHERE c.service_id = s.id)"
        )
    ).fetchall()
    for r in rows:
        conn.execute(
            text(
                "INSERT INTO service_clients "
                "(service_id, inbound_id, protocol, label, client_uuid, email, "
                "config_link, used_bytes, enabled, created_at) VALUES "
                "(:sid, :inb, '', 'کانفیگ', :uuid, :email, :link, :used, 1, "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "sid": r[0], "inb": r[1], "uuid": r[2], "email": r[3],
                "link": r[4] or "", "used": r[5] or 0,
            },
        )


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(_migrate_gb_to_mb)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_backfill_service_clients)


async def dispose_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
