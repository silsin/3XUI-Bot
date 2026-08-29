"""نقطه ورود ربات فروش VPN."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
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

    web_runner = None
    if settings.sub_public_url:
        import os

        from app.web import start_web

        ssl_ctx = None
        cert, key = settings.sub_tls_cert, settings.sub_tls_key
        if cert and key and os.path.exists(cert) and os.path.exists(key):
            import ssl

            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(certfile=cert, keyfile=key)
            logger.info("subscription server TLS enabled")
        elif cert or key:
            logger.warning("TLS cert/key configured but not found; serving HTTP")

        # پورت داخلی ثابت است؛ نگاشت پورت میزبان در docker-compose انجام می‌شود
        web_runner = await start_web("0.0.0.0", 8080, ssl_ctx)

    try:
        # اولین تماس با تلگرام؛ اعتبار توکن اینجا مشخص می‌شود
        me = await bot.get_me()
        logger.info("logged in as @%s (id=%s)", me.username, me.id)
        await _set_commands(bot)
        logger.info("bot starting; admins=%s", settings.admin_ids)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except TelegramUnauthorizedError:
        logger.error(
            "❌ توکن ربات نامعتبر است. مقدار BOT_TOKEN را در فایل .env بررسی کنید "
            "و دوباره اجرا کنید. (توکن را از @BotFather بگیرید)"
        )
    finally:
        scheduler.shutdown(wait=False)
        if web_runner is not None:
            await web_runner.cleanup()
        await close_provider()
        await dispose_db()
        await bot.session.close()
        logger.info("bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
