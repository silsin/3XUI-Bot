"""کلاینت پنل x-ui نسخه ۱.x (vaxilu) — مسیرهای API زیر /xui/ هستند.

تفاوت‌ها با 3x-ui:
- لیست inbound با POST /xui/inbound/list
- افزودن کلاینت: POST /xui/inbound/addClient
- حذف کلاینت:  POST /xui/inbound/{id}/delClient/{uuid}
- ویرایش کلاینت: POST /xui/inbound/updateClient/{uuid}
- endpoint مستقل مصرف/ریست کلاینت وجود ندارد؛ مصرف از فیلد clientStats
  همان inbound خوانده می‌شود.
"""

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

GB = 1024 ** 3


def _loads(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("failed to decode panel json field")
    return {}


class XuiLegacyClient:
    """پوشش API پنل x-ui 1.x."""

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
                follow_redirects=True,
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
            logger.info("x-ui login ok")

    async def _post(
        self, path: str, data: dict | None = None, _retry: bool = True
    ) -> dict:
        if not self._logged_in:
            await self.login()

        resp = await self._http().post(f"{self._root}{path}", data=data)

        if "application/json" not in resp.headers.get("content-type", ""):
            # نشست منقضی شده؛ صفحه لاگین برگشته
            if _retry:
                logger.info("x-ui session expired, re-login")
                self._logged_in = False
                await self.login()
                return await self._post(path, data=data, _retry=False)
            raise VpnError(f"{path} -> non-json response")

        payload = resp.json()
        if not payload.get("success", False):
            raise VpnError(f"{path} -> {payload.get('msg', 'panel error')}")
        return payload

    # ---------- inbound ----------

    async def list_inbounds(self) -> list[dict]:
        payload = await self._post("/xui/inbound/list")
        return payload.get("obj") or []

    async def get_inbound(self, inbound_id: int) -> dict:
        for inbound in await self.list_inbounds():
            if int(inbound.get("id")) == int(inbound_id):
                return inbound
        raise VpnError(f"inbound {inbound_id} not found")

    async def ping(self) -> bool:
        await self.login()
        await self.list_inbounds()
        return True

    # ---------- کلاینت ----------

    async def create_client(
        self,
        inbound_id: int,
        email: str,
        days: int,
        traffic_gb: int,
        device_limit: int = 0,
        telegram_id: int | None = None,
    ) -> ProvisionResult:
        inbound = await self.get_inbound(inbound_id)
        protocol = (inbound.get("protocol") or "vmess").lower()

        client_uuid = str(uuid_lib.uuid4())
        sub_id = secrets.token_hex(8)
        expiry_ms = int((time.time() + days * 86400) * 1000) if days > 0 else 0

        client: dict[str, Any] = {
            "id": client_uuid,
            "email": email,
            "totalGB": max(traffic_gb, 0) * GB,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": str(telegram_id or ""),
            "subId": sub_id,
            "reset": 0,
        }
        if device_limit > 0:
            client["limitIp"] = device_limit

        stream = _loads(inbound.get("streamSettings"))
        if protocol == "vless" and stream.get("security") == "reality":
            client["flow"] = "xtls-rprx-vision"
        if protocol in {"trojan", "shadowsocks"}:
            client["password"] = secrets.token_urlsafe(12)

        await self._post(
            "/xui/inbound/addClient",
            data={"id": inbound_id, "settings": json.dumps({"clients": [client]})},
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
        )

    def _build_link(self, inbound: dict, client: dict, remark: str) -> str:
        host = self._s.xui_node_host or inbound.get("listen") or ""
        if not host:
            host = self._s.xui_base_url.split("//")[-1].split(":")[0].split("/")[0]
        return build_link(
            protocol=(inbound.get("protocol") or "vmess").lower(),
            host=host,
            port=int(inbound.get("port") or 443),
            client=client,
            stream=_loads(inbound.get("streamSettings")),
            remark=remark,
        )

    def _find_client(self, inbound: dict, client_uuid: str, email: str) -> dict:
        clients = _loads(inbound.get("settings")).get("clients") or []
        for item in clients:
            if item.get("id") == client_uuid or item.get("email") == email:
                return item
        raise VpnError(f"client {email} not found in inbound {inbound.get('id')}")

    async def extend_client(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        add_days: int,
        add_traffic_gb: int,
        reset_traffic: bool = False,
    ) -> None:
        inbound = await self.get_inbound(inbound_id)
        client = dict(self._find_client(inbound, client_uuid, email))

        now_ms = int(time.time() * 1000)
        current = int(client.get("expiryTime") or 0)
        base = current if current > now_ms else now_ms
        client["expiryTime"] = base + add_days * 86400_000 if add_days > 0 else 0

        if add_traffic_gb > 0:
            current_total = int(client.get("totalGB") or 0)
            client["totalGB"] = (
                add_traffic_gb * GB if reset_traffic
                else current_total + add_traffic_gb * GB
            )
        elif reset_traffic:
            client["totalGB"] = 0
        client["enable"] = True

        await self._post(
            f"/xui/inbound/updateClient/{client_uuid}",
            data={"id": inbound_id, "settings": json.dumps({"clients": [client]})},
        )
        # نکته: نسخه ۱.x endpoint ریست مصرف ندارد؛ شمارنده مصرف قبلی باقی می‌ماند.

    async def set_enabled(
        self, inbound_id: int, client_uuid: str, email: str, enabled: bool
    ) -> None:
        inbound = await self.get_inbound(inbound_id)
        client = dict(self._find_client(inbound, client_uuid, email))
        client["enable"] = enabled
        await self._post(
            f"/xui/inbound/updateClient/{client_uuid}",
            data={"id": inbound_id, "settings": json.dumps({"clients": [client]})},
        )

    async def delete_client(self, inbound_id: int, client_uuid: str) -> None:
        await self._post(f"/xui/inbound/{inbound_id}/delClient/{client_uuid}")

    async def get_usage(self, email: str) -> UsageInfo:
        """مصرف از clientStats همان inbound خوانده می‌شود (اسکن همه inboundها)."""
        try:
            inbounds = await self.list_inbounds()
        except VpnError:
            return UsageInfo(found=False)

        for inbound in inbounds:
            for stat in inbound.get("clientStats") or []:
                if stat.get("email") == email:
                    return UsageInfo(
                        up=int(stat.get("up") or 0),
                        down=int(stat.get("down") or 0),
                        total=int(stat.get("total") or 0),
                        expiry_ms=int(stat.get("expiryTime") or 0),
                        enable=bool(stat.get("enable", True)),
                        found=True,
                        extra=stat,
                    )
        return UsageInfo(found=False)
