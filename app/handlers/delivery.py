"""ارسال کانفیگ به کاربر - مشترک بین تست، خرید و تمدید."""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Service
from app.services import settings_service as cfg
from app.texts import S_CONFIG_CAPTION
from app.utils.formatting import days_left_text, render, traffic

logger = logging.getLogger(__name__)


async def send_config(bot: Bot, chat_id: int, service: Service, session) -> None:
    """کانفیگ‌های سرویس را برای کاربر می‌فرستد (همه پروتکل‌ها برای تست)."""
    svc = (
        await session.execute(
            select(Service)
            .where(Service.id == service.id)
            .options(selectinload(Service.clients))
        )
    ).scalar_one_or_none() or service

    clients = sorted(getattr(svc, "clients", []), key=lambda c: c.id)
    primary_link = clients[0].config_link if clients else svc.config_link

    template = await cfg.get(session, S_CONFIG_CAPTION)
    text = render(
        template,
        title=svc.title,
        days=days_left_text(svc.expires_at),
        traffic=traffic(svc.traffic_mb),
        link=primary_link,
    )
    await bot.send_message(chat_id, text, disable_web_page_preview=True)

    if len(clients) > 1:
        lines = ["🔐 <b>همه کانفیگ‌ها</b> — اگر یکی وصل نشد، دیگری را امتحان کنید:"]
        for c in clients:
            label = c.label or (c.protocol or "config").upper()
            lines.append(f"\n▫️ <b>{label}</b>\n<code>{c.config_link}</code>")
        await bot.send_message(
            chat_id, "\n".join(lines), disable_web_page_preview=True
        )

    if svc.sub_link:
        await bot.send_message(
            chat_id,
            f"🔗 لینک اشتراک (Subscription):\n<code>{svc.sub_link}</code>",
            disable_web_page_preview=True,
        )
