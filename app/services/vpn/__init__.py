from app.config import get_settings
from app.services.vpn.base import ProvisionResult, UsageInfo, VpnError, VpnProvider
from app.services.vpn.xui import XuiClient
from app.services.vpn.xui3 import Xui3Client
from app.services.vpn.xui_legacy import XuiLegacyClient
from app.services.vpn.xui2 import Xui2Client

_provider: VpnProvider | None = None
_provider2: Xui2Client | None = None

_LEGACY_VARIANTS = {"legacy", "xui", "vaxilu", "1.x", "1x"}
# پنل 3x-ui نسخه 3 (3.8.x) با REST API جدید
_V3_VARIANTS = {"xui3", "v3", "3.8", "3x", "mhsanaei3"}


def _build_provider() -> VpnProvider:
    variant = get_settings().xui_variant.strip().lower()
    if variant in _V3_VARIANTS:
        return Xui3Client()
    if variant in _LEGACY_VARIANTS:
        return XuiLegacyClient()
    return XuiClient()


def get_provider() -> VpnProvider:
    global _provider
    if _provider is None:
        _provider = _build_provider()
    return _provider


def get_provider2() -> Xui2Client | None:
    """دریافت پنل دوم VPN (اگر فعال باشد)."""
    global _provider2
    settings = get_settings()
    if not settings.xui2_enabled:
        return None
    if _provider2 is None:
        _provider2 = Xui2Client()
    return _provider2


async def close_provider() -> None:
    global _provider, _provider2
    if _provider is not None:
        await _provider.close()
        _provider = None
    if _provider2 is not None:
        await _provider2.close()
        _provider2 = None


__all__ = [
    "ProvisionResult",
    "UsageInfo",
    "VpnError",
    "VpnProvider",
    "XuiClient",
    "Xui3Client",
    "XuiLegacyClient",
    "Xui2Client",
    "get_provider",
    "get_provider2",
    "close_provider",
]
