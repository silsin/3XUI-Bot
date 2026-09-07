from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class VpnError(RuntimeError):
    """خطای عمومی در ارتباط با پنل."""


@dataclass(slots=True)
class ProvisionResult:
    """نتیجه ساخت یک کلاینت روی پنل."""

    uuid: str
    email: str
    sub_id: str
    inbound_id: int
    config_link: str
    sub_link: str = ""
    protocol: str = ""


@dataclass(slots=True)
class UsageInfo:
    """مصرف و وضعیت یک کلاینت."""

    up: int = 0
    down: int = 0
    total: int = 0
    expiry_ms: int = 0
    enable: bool = True
    found: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def used_bytes(self) -> int:
        return self.up + self.down


class VpnProvider(Protocol):
    """قرارداد مشترک برای پنل‌ها تا تعویض پنل ساده باشد."""

    async def create_client(
        self,
        inbound_id: int,
        email: str,
        days: int,
        traffic_mb: int,
        device_limit: int = 0,
        telegram_id: int | None = None,
        sub_id: str | None = None,
    ) -> ProvisionResult: ...

    async def extend_client(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        add_days: int,
        add_traffic_mb: int,
        reset_traffic: bool = False,
    ) -> None: ...

    async def set_quota_mb(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        traffic_mb: int,
    ) -> None:
        """سهمیه ترافیک کلاینت را به مقدار مطلق (مگابایت) تنظیم می‌کند.
        0 یعنی نامحدود.
        """
        ...

    async def get_usage(self, email: str) -> UsageInfo: ...

    async def get_all_usage(self) -> dict[str, UsageInfo]: ...

    async def delete_client(self, inbound_id: int, client_uuid: str) -> None: ...

    async def set_enabled(
        self, inbound_id: int, client_uuid: str, email: str, enabled: bool
    ) -> None: ...

    async def close(self) -> None: ...
