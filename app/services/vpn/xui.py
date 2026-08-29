"""کلاینت ارتباط با پنل 3x-ui."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid as uuid_lib
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.vpn.base import ProvisionResult, UsageInfo, VpnError
from app.services.vpn.links import build_link

logger = logging.getLogger(__name__)

MB = 1024 ** 2


def _loads(raw: Any) -> dict:
    """فیلدهایی مثل settings و streamSettings در پنل رشته JSON هستند."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("failed to decode panel json field")
    return {}


class XuiClient:
    """
    پوشش نازک روی API پنل 3x-ui.

    نکات مهم:
    - نشست بر پایه کوکی است؛ در صورت انقضا یک‌بار خودکار لاگین مجدد می‌شود.
    - مقدار totalGB در پنل به **بایت** است (نام فیلد گمراه‌کننده است).
    - expiryTime تایم‌استمپ **میلی‌ثانیه** است. صفر یعنی بدون انقضا.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        base = self._s.xui_base_url.rstrip("/")
        path = self._s.xui_web_base_path.strip("/")
        self._root = f"{base}/{path}" if path else base
        self._client: httpx.AsyncClient | None = None
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    # ---------- زیرساخت ----------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(25.0),
                verify=self._s.xui_verify_ssl,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._logged_in = False

    async def login(self) -> None:
        async with self._login_lock:
            resp = await self._http().post(
                f"{self._root}/login",
                data={
                    "username": self._s.xui_username,
                    "password": self._s.xui_password,
                },
            )
            if resp.status_code != 200:
                raise VpnError(f"login failed: HTTP {resp.status_code}")
            try:
                payload = resp.json()
            except ValueError as exc:
                raise VpnError("login failed: unexpected response") from exc
            if not payload.get("success"):
                raise VpnError(f"login rejected: {payload.get('msg', 'unknown')}")
            self._logged_in = True
            logger.info("xui login ok")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        _retry: bool = True,
    ) -> dict:
        if not self._logged_in:
            await self.login()

        url = f"{self._root}{path}"
        resp = await self._http().request(method, url, json=json_body)

        # نشست منقضی شده: پنل به صفحه لاگین ریدایرکت می‌کند یا HTML می‌دهد
        session_dead = resp.status_code in (301, 302, 307, 401, 403) or (
            "application/json" not in resp.headers.get("content-type", "")
        )
        if session_dead and _retry:
            logger.info("xui session expired, re-login")
            self._logged_in = False
            await self.login()
            return await self._request(method, path, json_body=json_body, _retry=False)

        if resp.status_code >= 400:
            raise VpnError(f"{path} -> HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise VpnError(f"{path} -> non-json response") from exc

        if not payload.get("success", False):
            raise VpnError(f"{path} -> {payload.get('msg', 'panel error')}")
        return payload

    # ---------- inbound ----------

    async def get_inbound(self, inbound_id: int) -> dict:
        payload = await self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")
        inbound = payload.get("obj") or {}
        if not inbound:
            raise VpnError(f"inbound {inbound_id} not found")
        return inbound

    async def list_inbounds(self) -> list[dict]:
        payload = await self._request("GET", "/panel/api/inbounds/list")
        return payload.get("obj") or []

    async def ping(self) -> bool:
        """برای تست اتصال از پنل ادمین."""
        await self.login()
        await self.list_inbounds()
        return True

    # ---------- کلاینت ----------

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
        inbound = await self.get_inbound(inbound_id)
        protocol = (inbound.get("protocol") or "vless").lower()

        client_uuid = str(uuid_lib.uuid4())
        sub_id = sub_id or secrets.token_hex(8)
        expiry_ms = int((time.time() + days * 86400) * 1000) if days > 0 else 0

        client: dict[str, Any] = {
            "id": client_uuid,
            "email": email,
            "enable": True,
            "flow": "",
            "limitIp": max(device_limit, 0),
            "totalGB": max(traffic_mb, 0) * MB,
            "expiryTime": expiry_ms,
            "tgId": str(telegram_id or ""),
            "subId": sub_id,
            "reset": 0,
        }

        # reality معمولاً به flow نیاز دارد
        stream = _loads(inbound.get("streamSettings"))
        if protocol == "vless" and stream.get("security") == "reality":
            client["flow"] = "xtls-rprx-vision"
        if protocol in {"trojan", "shadowsocks"}:
            client["password"] = secrets.token_urlsafe(12)

        await self._request(
            "POST",
            "/panel/api/inbounds/addClient",
            json_body={
                "id": inbound_id,
                "settings": json.dumps({"clients": [client]}),
            },
        )

        link = self._build_link(inbound, client, email)
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
            protocol=protocol,
        )

    def _build_link(self, inbound: dict, client: dict, remark: str) -> str:
        host = self._s.xui_node_host or inbound.get("listen") or ""
        if not host:
            # آخرین تلاش: دامنه پنل
            host = (
                self._s.xui_base_url.split("//")[-1].split(":")[0].split("/")[0]
            )
        return build_link(
            protocol=(inbound.get("protocol") or "vless").lower(),
            host=host,
            port=int(inbound.get("port") or 443),
            client=client,
            stream=_loads(inbound.get("streamSettings")),
            remark=remark,
        )

    async def _find_client(self, inbound: dict, client_uuid: str, email: str) -> dict:
        clients = _loads(inbound.get("settings")).get("clients") or []
        for item in clients:
            if item.get("id") == client_uuid or item.get("email") == email:
                return item
        raise VpnError(f"client {email} not found in inbound {inbound.get('id')}")

    async def build_client_link(
        self, inbound_id: int, client_uuid: str, email: str
    ) -> str:
        """لینک را از روی کلاینت موجود پنل بازسازی می‌کند (بدون ساخت مجدد)."""
        inbound = await self.get_inbound(inbound_id)
        client = await self._find_client(inbound, client_uuid, email)
        return self._build_link(inbound, client, email)

    async def extend_client(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        add_days: int,
        add_traffic_mb: int,
        reset_traffic: bool = False,
    ) -> None:
        """تمدید: روزها به انقضای فعلی (یا از الان اگر گذشته) اضافه می‌شود."""
        inbound = await self.get_inbound(inbound_id)
        client = dict(await self._find_client(inbound, client_uuid, email))

        now_ms = int(time.time() * 1000)
        current = int(client.get("expiryTime") or 0)
        base = current if current > now_ms else now_ms
        client["expiryTime"] = base + add_days * 86400_000 if add_days > 0 else 0

        if add_traffic_mb > 0:
            current_total = int(client.get("totalGB") or 0)
            client["totalGB"] = (
                add_traffic_mb * MB if reset_traffic
                else current_total + add_traffic_mb * MB
            )
        elif reset_traffic:
            client["totalGB"] = 0

        client["enable"] = True

        await self._request(
            "POST",
            f"/panel/api/inbounds/updateClient/{client_uuid}",
            json_body={
                "id": inbound_id,
                "settings": json.dumps({"clients": [client]}),
            },
        )

        if reset_traffic:
            await self.reset_traffic(inbound_id, email)

    async def set_enabled(
        self, inbound_id: int, client_uuid: str, email: str, enabled: bool
    ) -> None:
        inbound = await self.get_inbound(inbound_id)
        client = dict(await self._find_client(inbound, client_uuid, email))
        client["enable"] = enabled
        await self._request(
            "POST",
            f"/panel/api/inbounds/updateClient/{client_uuid}",
            json_body={
                "id": inbound_id,
                "settings": json.dumps({"clients": [client]}),
            },
        )

    async def reset_traffic(self, inbound_id: int, email: str) -> None:
        await self._request(
            "POST", f"/panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}"
        )

    async def delete_client(self, inbound_id: int, client_uuid: str) -> None:
        await self._request(
            "POST", f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}"
        )

    async def get_usage(self, email: str) -> UsageInfo:
        try:
            payload = await self._request(
                "GET", f"/panel/api/inbounds/getClientTraffics/{email}"
            )
        except VpnError:
            return UsageInfo(found=False)

        obj = payload.get("obj")
        if not obj:
            return UsageInfo(found=False)
        if isinstance(obj, list):
            obj = obj[0] if obj else {}
        return UsageInfo(
            up=int(obj.get("up") or 0),
            down=int(obj.get("down") or 0),
            total=int(obj.get("total") or 0),
            expiry_ms=int(obj.get("expiryTime") or 0),
            enable=bool(obj.get("enable", True)),
            found=True,
            extra=obj if isinstance(obj, dict) else {},
        )

    async def get_all_usage(self) -> dict[str, UsageInfo]:
        """نگاشت email → مصرف برای همه کلاینت‌ها با یک بار فراخوانی پنل."""
        result: dict[str, UsageInfo] = {}
        try:
            inbounds = await self.list_inbounds()
        except VpnError:
            return result
        for inbound in inbounds:
            for stat in inbound.get("clientStats") or []:
                email = stat.get("email")
                if not email:
                    continue
                result[email] = UsageInfo(
                    up=int(stat.get("up") or 0),
                    down=int(stat.get("down") or 0),
                    total=int(stat.get("total") or 0),
                    expiry_ms=int(stat.get("expiryTime") or 0),
                    enable=bool(stat.get("enable", True)),
                    found=True,
                    extra=stat,
                )
        return result
