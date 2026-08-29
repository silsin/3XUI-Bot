"""سرور اشتراک (subscription) داخلی ربات.

آدرس /sub/{sub_id} فهرست base64 همه کانفیگ‌های یک سرویس را برمی‌گرداند
(فرمت استاندارد subscription که v2rayNG و مشابه آن می‌فهمند). چون همه‌ی
کلاینت‌های یک سرویس sub_id مشترک دارند، این لینک همه‌ی پروتکل‌ها را می‌آورد.
"""

from __future__ import annotations

import base64
import logging

from aiohttp import web
from sqlalchemy import select

from app.db.models import Service, ServiceClient
from app.db.session import get_sessionmaker

logger = logging.getLogger(__name__)


async def _sub_handler(request: web.Request) -> web.Response:
    sub_id = request.match_info.get("sub_id", "")
    if not sub_id:
        return web.Response(status=404, text="not found")

    async with get_sessionmaker()() as session:
        service = (
            await session.execute(select(Service).where(Service.sub_id == sub_id))
        ).scalar_one_or_none()
        if service is None:
            return web.Response(status=404, text="not found")
        clients = list(
            (
                await session.execute(
                    select(ServiceClient).where(
                        ServiceClient.service_id == service.id
                    )
                )
            ).scalars().all()
        )

    links = "\n".join(c.config_link for c in clients if c.config_link)
    body = base64.b64encode(links.encode()).decode()
    return web.Response(text=body, content_type="text/plain")


def make_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/sub/{sub_id}", _sub_handler)
    return app


async def start_web(host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(make_web_app())
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("subscription server listening on %s:%s", host, port)
    return runner
