from __future__ import annotations

from pathlib import Path

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


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
