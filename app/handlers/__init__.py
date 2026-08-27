from aiogram import Router

from app.handlers import buy, common, misc, points, services, trial
from app.handlers.admin import get_admin_router


def get_root_router() -> Router:
    """ترتیب مهم است: ادمین و جریان‌های خاص قبل از fallback."""
    root = Router(name="root")

    # ادمین اول تا دکمه پنل مدیریت پیش از سایر متن‌ها گرفته شود
    root.include_router(get_admin_router())

    root.include_router(common.router)
    root.include_router(trial.router)
    root.include_router(buy.router)
    root.include_router(services.router)
    root.include_router(points.router)
    root.include_router(misc.router)

    # fallback باید آخر باشد
    root.include_router(common.fallback_router)
    return root
