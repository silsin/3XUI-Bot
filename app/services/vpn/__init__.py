from app.config import get_settings
from app.services.vpn.base import ProvisionResult, UsageInfo, VpnError, VpnProvider
from app.services.vpn.xui import XuiClient
from app.services.vpn.xui_legacy import XuiLegacyClient

_provider: VpnProvider | None = None

_LEGACY_VARIANTS = {"legacy", "xui", "vaxilu", "1.x", "1x"}


def _build_provider() -> VpnProvider:
    variant = get_settings().xui_variant.strip().lower()
    if variant in _LEGACY_VARIANTS:
        return XuiLegacyClient()
    return XuiClient()


def get_provider() -> VpnProvider:
    global _provider
    if _provider is None:
        _provider = _build_provider()
    return _provider


async def close_provider() -> None:
    global _provider
    if _provider is not None:
        await _provider.close()
        _provider = None


__all__ = [
    "ProvisionResult",
    "UsageInfo",
    "VpnError",
    "VpnProvider",
    "XuiClient",
    "XuiLegacyClient",
    "get_provider",
    "close_provider",
]
