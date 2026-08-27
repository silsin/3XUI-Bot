"""نقطه ورود ربات فروش VPN."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import get_settings
from app.db.session import dispose_db, get_sessionmaker, init_db
from app.handlers import get_root_router
from app.middlewares import DbSessionMiddleware, UserMiddleware
from app.scheduler import setup_scheduler
from app.services import settings_service as cfg
from app.services.vpn import close_provider


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="شروع / منوی اصلی"),
            BotCommand(command="menu", description="نمایش منو"),
            BotCommand(command="cancel", description="لغو عملیات جاری"),
        ]
    )


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("bot")

    await init_db()
    async with get_sessionmaker()() as session:
        await cfg.seed_defaults(session)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # میدلورها: نشست دیتابیس سپس کاربر، روی پیام و کالبک
    for observer in (dp.message, dp.callback_query):
        observer.middleware(DbSessionMiddleware())
        observer.middleware(UserMiddleware())

    dp.include_router(get_root_router())

    scheduler = setup_scheduler(bot, settings.timezone)
    scheduler.start()

    await _set_commands(bot)
    logger.info("bot starting; admins=%s", settings.admin_ids)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await close_provider()
        await dispose_db()
        await bot.session.close()
        logger.info("bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
