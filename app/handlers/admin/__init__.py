from aiogram import Router

from app.handlers.admin import (
    activity,
    approval,
    offers,
    panel,
    panels,
    referral_campaigns,
    transfer,
    wallet_management,
    wallet_topup_requests,
    withdrawals,
)


def get_admin_router() -> Router:
    router = Router(name="admin")
    router.include_router(approval.router)
    router.include_router(panel.router)
    router.include_router(panels.router)
    router.include_router(wallet_management.router)
    router.include_router(wallet_topup_requests.router)
    router.include_router(withdrawals.router)
    router.include_router(referral_campaigns.router)
    router.include_router(activity.router)
    router.include_router(offers.router)
    router.include_router(transfer.router)
    return router
