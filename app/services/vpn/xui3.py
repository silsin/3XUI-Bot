"""کلاینت ارتباط با پنل 3x-ui نسخه 3 (mhsanaei/3x-ui v3، پنل 3.8.x).

تفاوت‌های کلیدی با نسخه کلاسیک که در xui.py پیاده شده:
- احراز هویت با توکن Bearer انجام می‌شود، نه لاگین و کوکی.
- کلاینت‌ها دیگر داخل JSON اینباند نیستند؛ جدول جدا دارند و یک کلاینت
  می‌تواند به چند اینباند متصل باشد.
- لینک‌ها را خود پنل می‌سازد (clients/links/{email})، پس نیازی به
  ساخت دستی لینک از streamSettings نیست.
- واحد totalGB بایت و expiryTime میلی‌ثانیه است (مثل نسخه کلاسیک).

نکته مهم: آپدیت کلاینت در این نسخه «جایگزینی کامل» است نه patch؛
بنابراین هر تغییر ابتدا کلاینت خوانده و سپس وضعیت کامل ارسال می‌شود.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.vpn.base import ProvisionResult, UsageInfo, VpnError

logger = logging.getLogger(__name__)

MB = 1024 ** 2


class Xui3Client:
    """پوشش نازک روی REST API پنل 3x-ui v3."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        base = self._s.xui_base_url.rstrip("/")
        path = self._s.xui_web_base_path.strip("/")
        self._root = f"{base}/{path}" if path else base
        self._client: httpx.AsyncClient | None = None

    # ---------- زیرساخت ----------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json"}
            if self._s.xui_api_token:
                headers["Authorization"] = f"Bearer {self._s.xui_api_token}"
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(25.0),
                verify=self._s.xui_verify_ssl,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
    ) -> Any:
        url = f"{self._root}{path}"
        try:
            resp = await self._http().request(method, url, json=json_body)
        except httpx.HTTPError as exc:
            raise VpnError(f"{path} -> {exc}") from exc

        if resp.status_code in (401, 403):
            raise VpnError(
                f"{path} -> HTTP {resp.status_code} (توکن API نامعتبر یا غیرفعال است)"
            )
        if resp.status_code >= 400:
            raise VpnError(f"{path} -> HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise VpnError(f"{path} -> پاسخ JSON نبود") from exc

        if not payload.get("success", False):
            raise VpnError(f"{path} -> {payload.get('msg') or 'panel error'}")
        return payload.get("obj")
# ---------- inbound ----------

    async def list_inbounds(self) -> list[dict]:
        return await self._request("GET", "/panel/api/inbounds/list") or []

    async def ping(self) -> bool:
        """تست اتصال پنل از بخش ادمین."""
        await self.list_inbounds()
        return True

    async def ensure_share_addr(self) -> None:
        """اطمینان از وجود share address تا لینک‌ها host خالی نداشته باشند.

        اگر برای اینباندها گروه host وجود نداشته باشد یکی می‌سازد. این کار
        idempotent است و در هر بوت اجرا می‌شود.
        """
        host = (self._s.xui_node_host or "").strip()
        if not host or not self._s.xui_api_token:
            return
        try:
            inbounds = await self.list_inbounds()
            ids = [int(i["id"]) for i in inbounds if i.get("id") is not None]
            if not ids:
                return
            groups = await self._request("GET", "/panel/api/hosts/list") or []
            covered = {int(i) for g in groups for i in (g.get("inboundIds") or [])}
            if ids and all(i in covered for i in ids):
                logger.info("share address already configured for inbounds %s", ids)
                return
            await self._request(
                "POST",
                "/panel/api/hosts/add",
                json_body={
                    "inboundIds": ids,
                    "remark": "bot-node",
                    "hosts": [host],
                    "port": 0,
                    "security": "same",
                },
            )
            logger.info("share address %s applied to inbounds %s", host, ids)
        except VpnError as exc:
            # نباید بوت ربات را متوقف کند
            logger.warning("could not ensure share address: %s", exc)

    # ---------- کلاینت ----------

    async def _get_client(self, email: str) -> dict:
        obj = await self._request("GET", f"/panel/api/clients/get/{email}")
        if not obj:
            raise VpnError(f"کلاینت {email} یافت نشد")
        return obj.get("client") or {}

    # فیلدهایی که اسکیمای Client پنل می‌پذیرد (به‌جز id که جدا مدیریت می‌شود)
    _CLIENT_FIELDS = (
        "adTag",
        "allowedIPs",
        "auth",
        "comment",
        "email",
        "enable",
        "expiryTime",
        "flow",
        "forwardedPorts",
        "group",
        "keepAlive",
        "limitIp",
        "limitHwid",
        "password",
        "preSharedKey",
        "privateKey",
        "publicKey",
        "reset",
        "resetDay",
        "resetMax",
        "secret",
        "security",
        "subId",
        "tgId",
        "totalGB",
        "trafficReset",
        "trafficResetDay",
    )

    async def _mutate(self, email: str, **changes: Any) -> dict:
        """خواندن، اعمال تغییر و ارسال وضعیت کامل.

        چون update در این پنل جایگزینی کامل است، اگر فقط فیلدهای تغییرکرده
        را بفرستیم بقیه فیلدها (سهمیه و انقضا) صفر می‌شوند. به همین دلیل
        کلاینت موجود خوانده و فیلدهای فقط-خواندنی حذف می‌شوند.
        """
        current = dict(await self._get_client(email))
        current.update(changes)

        # فقط فیلدهایی که اسکیمای Client می‌پذیرد؛ پاسخ پنل چند فیلد
        # فقط-خواندنی و چند نوع ناسازگار دارد که update آن‌ها را رد می‌کند.
        payload: dict[str, Any] = {}
        for key in self._CLIENT_FIELDS:
            if key == "id":
                continue
            if key in current:
                payload[key] = current[key]
        payload["id"] = str(current.get("uuid") or current.get("id") or "")

        # در پاسخ رشته است ولی در update آرایه رشته می‌خواهد
        allowed = payload.get("allowedIPs")
        if isinstance(allowed, str):
            payload["allowedIPs"] = [allowed] if allowed.strip() else []
        tg = payload.get("tgId")
        if isinstance(tg, str):
            payload["tgId"] = int(tg) if tg.strip() else 0
        await self._request(
            "POST", f"/panel/api/clients/update/{email}", json_body=payload
        )
        return payload

    async def create_client(
        self,
        inbound_id: int,
        email: str,
        days: int,
        traffic_mb: int,
        device_limit: int = 0,
        telegram_id: int | None = None,
        sub_id: str | None = None,
    ) -> ProvisionResult:
        sub_id = sub_id or secrets.token_hex(8)
        expiry_ms = int((time.time() + days * 86400) * 1000) if days > 0 else 0

        body = {
            "client": {
                "email": email,
                "subId": sub_id,
                "enable": True,
                "totalGB": max(traffic_mb, 0) * MB,
                "expiryTime": expiry_ms,
                # در v3 محدودیت دستگاه با HWID بیان می‌شود
                "limitHwid": max(device_limit, 0),
                "limitIp": 0,
                "tgId": int(telegram_id or 0),
            },
            "inboundIds": [inbound_id],
        }
        await self._request("POST", "/panel/api/clients/add", json_body=body)

        # پنل uuid را خودش می‌سازد؛ برای ثبت در دیتابیس باید بخوانیمش
        client = await self._get_client(email)
        # توجه: client["id"] شماره رکورد است؛ uuid واقعی در فیلد uuid است
        client_uuid = str(client.get("uuid") or "")
        link = await self.build_client_link(inbound_id, client_uuid, email)

        sub_link = ""
        if self._s.xui_sub_base_url:
            sub_link = f"{self._s.xui_sub_base_url.rstrip('/')}/{sub_id}"

        return ProvisionResult(
            uuid=client_uuid,
            email=email,
            sub_id=sub_id,
            inbound_id=inbound_id,
            config_link=link,
            sub_link=sub_link,
            protocol="",
        )

    async def build_client_link(
        self, inbound_id: int, client_uuid: str, email: str
    ) -> str:
        """لینک‌های آماده که خود پنل ساخته است."""
        links = await self._request("GET", f"/panel/api/clients/links/{email}") or []
        if not links:
            raise VpnError(f"پنل لینکی برای {email} برنگرداند")
        return str(links[0])

    async def extend_client(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        add_days: int,
        add_traffic_mb: int,
        reset_traffic: bool = False,
    ) -> None:
        current = await self._get_client(email)

        now_ms = int(time.time() * 1000)
        cur_exp = int(current.get("expiryTime") or 0)
        base = cur_exp if cur_exp > now_ms else now_ms
        expiry = base + add_days * 86400_000 if add_days > 0 else 0

        total = int(current.get("totalGB") or 0)
        if add_traffic_mb > 0:
            total = (
                add_traffic_mb * MB if reset_traffic else total + add_traffic_mb * MB
            )
        elif reset_traffic:
            total = 0

        await self._mutate(email, expiryTime=expiry, totalGB=total, enable=True)

        if reset_traffic:
            await self.reset_traffic(inbound_id, email)

    async def set_quota_mb(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        traffic_mb: int,
    ) -> None:
        await self._mutate(email, totalGB=max(traffic_mb, 0) * MB)

    async def set_enabled(
        self, inbound_id: int, client_uuid: str, email: str, enabled: bool
    ) -> None:
        await self._mutate(email, enable=enabled)

    async def reset_traffic(self, inbound_id: int, email: str) -> None:
        await self._request("POST", f"/panel/api/clients/resetTraffic/{email}")

    async def delete_client(self, inbound_id: int, client_uuid: str) -> None:
        # این نسخه کلاینت را با ایمیل می‌شناسد
        try:
            await self._request("POST", f"/panel/api/clients/del/{client_uuid}")
        except VpnError as exc:
            logger.warning("delete failed for %s: %s", client_uuid, exc)

    async def get_usage(self, email: str) -> UsageInfo:
        obj = await self._request("GET", f"/panel/api/clients/traffic/{email}")
        if not obj:
            return UsageInfo(found=False)
        return UsageInfo(
            up=int(obj.get("up") or 0),
            down=int(obj.get("down") or 0),
            total=int(obj.get("total") or 0),
            expiry_ms=int(obj.get("expiryTime") or 0),
            enable=bool(obj.get("enable", True)),
        )

    async def get_all_usage(self) -> dict[str, UsageInfo]:
        clients = await self._request("GET", "/panel/api/clients/list") or []
        out: dict[str, UsageInfo] = {}
        for c in clients:
            traffic = c.get("traffic") or {}
            out[c["email"]] = UsageInfo(
                up=int(traffic.get("up") or 0),
                down=int(traffic.get("down") or 0),
                total=int(c.get("totalGB") or 0),
                expiry_ms=int(c.get("expiryTime") or 0),
                enable=bool(c.get("enable", True)),
            )
        return out
