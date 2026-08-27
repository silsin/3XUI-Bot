from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting
from app.texts import DEFAULT_SETTINGS


async def seed_defaults(session: AsyncSession) -> None:
    """مقادیر پیش‌فرض را برای کلیدهای جدید درج می‌کند (بدون بازنویسی)."""
    existing = set(
        (await session.execute(select(Setting.key))).scalars().all()
    )
    added = False
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            session.add(Setting(key=key, value=value))
            added = True
    if added:
        await session.commit()


async def get(session: AsyncSession, key: str, default: str = "") -> str:
    row = await session.get(Setting, key)
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row.value


async def get_int(session: AsyncSession, key: str, default: int = 0) -> int:
    raw = await get(session, key, str(default))
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


async def get_bool(session: AsyncSession, key: str, default: bool = False) -> bool:
    raw = (await get(session, key, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on", "بله"}


async def set_value(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def get_many(session: AsyncSession, keys: list[str]) -> dict[str, str]:
    rows = (
        await session.execute(select(Setting).where(Setting.key.in_(keys)))
    ).scalars().all()
    found = {row.key: row.value for row in rows}
    return {key: found.get(key, DEFAULT_SETTINGS.get(key, "")) for key in keys}
