from aiogram import Router

from app.handlers.admin import activity, approval, channel, offers, panel


def get_admin_router() -> Router:
    router = Router(name="admin")
    router.include_router(approval.router)
    router.include_router(panel.router)
    router.include_router(activity.router)
    router.include_router(offers.router)
    router.include_router(channel.router)
    return router
