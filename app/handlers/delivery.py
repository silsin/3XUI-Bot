"""ارسال کانفیگ به کاربر - مشترک بین تست، خرید و تمدید."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import (
    BufferedInputFile,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Service
from app.services import settings_service as cfg
from app.texts import S_CONFIG_CAPTION
from app.utils.formatting import days_left_text, render, traffic
from app.utils.qr import make_qr_png

logger = logging.getLogger(__name__)


async def send_config_message(bot: Bot, chat_id: int, label: str, link: str) -> None:
    """یک QR + یک پیام حاوی «فقط» لینک (برای کپی تمیز و ایمپورت بدون خطا)."""
    if not link:
        return
    try:
        qr = BufferedInputFile(make_qr_png(link), filename=f"{label}.png")
        await bot.send_photo(
            chat_id,
            qr,
            caption=(
                f"🔐 <b>{label}</b>\n"
                "QR را اسکن کنید یا لینک زیر را کپی کرده و در برنامه "
                "«Import from clipboard» بزنید 👇"
            ),
        )
    except Exception:  # noqa: BLE001 — اگر QR نشد، فقط لینک را می‌فرستیم
        logger.exception("qr send failed")

    markup = None
    if len(link) <= 256:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="📋 کپی کانفیگ", copy_text=CopyTextButton(text=link)
                )
            ]]
        )
    # پیام فقط-لینک: کپی کل پیام هم دقیقاً همان لینک می‌شود
    await bot.send_message(
        chat_id, f"<code>{link}</code>",
        reply_markup=markup, disable_web_page_preview=True,
    )


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

    if clients:
        for c in clients:
            label = c.label or (c.protocol or "config").upper()
            await send_config_message(bot, chat_id, label, c.config_link)
    elif svc.config_link:
        await send_config_message(bot, chat_id, "کانفیگ", svc.config_link)

    from app.handlers.services import sub_link_for

    sub = sub_link_for(svc)
    if sub:
        await bot.send_message(
            chat_id,
            "🔗 <b>لینک اشتراک (همه پروتکل‌ها)</b> — به‌عنوان Subscription اضافه کنید:",
        )
        await bot.send_message(
            chat_id, f"<code>{sub}</code>", disable_web_page_preview=True
        )
