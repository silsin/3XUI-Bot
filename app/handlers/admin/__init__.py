from aiogram import Router

from app.handlers.admin import activity, approval, panel


def get_admin_router() -> Router:
    router = Router(name="admin")
    router.include_router(approval.router)
    router.include_router(panel.router)
    router.include_router(activity.router)
    return router
