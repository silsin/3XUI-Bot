"""ارسال کانفیگ به کاربر - مشترک بین تست، خرید و تمدید."""

from __future__ import annotations

import logging

from aiogram import Bot

from app.db.models import Service
from app.services import settings_service as cfg
from app.texts import S_CONFIG_CAPTION
from app.utils.formatting import days_left_text, render, traffic

logger = logging.getLogger(__name__)


async def send_config(bot: Bot, chat_id: int, service: Service, session) -> None:
    """کانفیگ سرویس را به‌صورت پیام قابل کپی برای کاربر می‌فرستد."""
    template = await cfg.get(session, S_CONFIG_CAPTION)
    text = render(
        template,
        title=service.title,
        days=days_left_text(service.expires_at),
        traffic=traffic(service.traffic_mb),
        link=service.config_link,
    )
    await bot.send_message(chat_id, text, disable_web_page_preview=True)
    if service.sub_link:
        await bot.send_message(
            chat_id,
            f"🔗 لینک اشتراک (Subscription):\n<code>{service.sub_link}</code>",
            disable_web_page_preview=True,
        )
