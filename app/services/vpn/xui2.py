"""کلاینت ارتباط با پنل VPN دوم (پشتیبان)."""

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


class Xui2Client:
    """
    پوشش نازک روی API پنل دوم.
    
    نکات مهم:
    - نشست بر پایه کوکی است؛ در صورت انقضا یک‌بار خودکار لاگین مجدد می‌شود.
    - مقدار totalGB در پنل به **بایت** است (نام فیلد گمراه‌کننده است).
    - expiryTime تایم‌استمپ **میلی‌ثانیه** است. صفر یعنی بدون انقضا.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        base = self._s.xui2_base_url.rstrip("/")
        path = self._s.xui2_web_base_path.strip("/")
        self._root = f"{base}/{path}" if path else base
        self._client: httpx.AsyncClient | None = None
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    # ---------- زیرساخت ----------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(25.0),
                verify=self._s.xui2_verify_ssl,
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
                    "username": self._s.xui2_username,
                    "password": self._s.xui2_password,
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
            logger.info("xui2 login ok")

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

        url = f"{self._root}/{path.lstrip('/')}"
        kwargs: dict = {"headers": {}}
        if json_body is not None:
            kwargs["json"] = json_body

        resp = await self._http().request(method, url, **kwargs)

        if resp.status_code == 401 and _retry:
            logger.info("xui2 session expired, re-login")
            self._logged_in = False
            return await self._request(method, path, json_body=json_body, _retry=False)

        if resp.status_code != 200:
            raise VpnError(f"{method} {path} failed: HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise VpnError(f"{method} {path} failed: invalid JSON") from exc

        if not data.get("success"):
            raise VpnError(f"{method} {path} failed: {data.get('msg', 'unknown')}")

        return data.get("obj", data)

    # ---------- عملیات‌های اصلی ----------

    async def get_inbounds(self) -> list[dict]:
        """لیست همه inbounds."""
        return await self._request("GET", "xui/inbounds")

    async def get_inbound(self, inbound_id: int) -> dict | None:
        """یک inbound خاص."""
        inbounds = await self.get_inbounds()
        for i in inbounds:
            if i.get("id") == inbound_id:
                return i
        return None

    async def create_client(
        self,
        inbound_id: int,
        email: str,
        days: int,
        traffic_mb: int,
        device_limit: int = 0,
        telegram_id: int = 0,
    ) -> ProvisionResult:
        """ساخت کلاینت جدید."""
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            raise VpnError(f"inbound {inbound_id} not found")

        settings = _loads(inbound.get("settings", "{}"))
        if "clients" not in settings:
            settings["clients"] = []

        # ساخت کلاینت
        client = {
            "id": str(uuid_lib.uuid4()),
            "email": email,
            "enable": True,
            "flow": "",
            "limitIp": device_limit,
            "totalGB": traffic_mb * MB,
            "expiryTime": int(time.time() * 1000) + days * 86400000,
            "tgId": str(telegram_id) if telegram_id else "",
            "subId": secrets.token_hex(8),
        }

        settings["clients"].append(client)

        # به‌روزرسانی inbound
        await self._request(
            "PUT",
            f"xui/inbound/{inbound_id}",
            json_body={
                "enable": inbound.get("enable", True),
                "up": inbound.get("up", 0),
                "down": inbound.get("down", 0),
                "total": inbound.get("total", 0),
                "remark": inbound.get("remark", ""),
                "listen": inbound.get("listen", ""),
                "stream": inbound.get("stream", ""),
                "settings": json.dumps(settings),
                "tag": inbound.get("tag", ""),
            },
        )

        # ساخت لینک
        protocol = inbound.get("protocol", "")
        client_uuid = client["id"]
        
        host = self._s.xui_node_host or self._s.xui_base_url.replace("https://", "").replace("http://", "")
        port = inbound.get("port", 443)
        
        # لینک کانفیگ
        config_link = build_link(
            protocol=protocol,
            host=host,
            port=port,
            uuid=client_uuid,
            alter_id=settings.get("alterId", 0),
            security=settings.get("security", "auto"),
            flow=settings.get("flow", ""),
            sni=settings.get("serverName", ""),
        )
        
        # لینک اشتراک
        sub_link = f"{self._s.xui2_sub_base_url}/{client['subId']}"

        logger.info("xui2 client created: %s", email)

        return ProvisionResult(
            uuid=client_uuid,
            email=email,
            sub_id=client["subId"],
            inbound_id=inbound_id,
            config_link=config_link,
            sub_link=sub_link,
            protocol=protocol,
        )

    async def delete_client(self, inbound_id: int, client_uuid: str) -> None:
        """حذف کلاینت."""
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return

        settings = _loads(inbound.get("settings", "{}"))
        if "clients" not in settings:
            return

        settings["clients"] = [
            c for c in settings["clients"] if c.get("id") != client_uuid
        ]

        await self._request(
            "PUT",
            f"xui/inbound/{inbound_id}",
            json_body={
                "enable": inbound.get("enable", True),
                "up": inbound.get("up", 0),
                "down": inbound.get("down", 0),
                "total": inbound.get("total", 0),
                "remark": inbound.get("remark", ""),
                "listen": inbound.get("listen", ""),
                "stream": inbound.get("stream", ""),
                "settings": json.dumps(settings),
                "tag": inbound.get("tag", ""),
            },
        )

        logger.info("xui2 client deleted: %s", client_uuid)

    async def extend_client(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        add_days: int,
        add_traffic_mb: int,
        reset_traffic: bool = False,
    ) -> None:
        """تمدید یا افزودن حجم."""
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            raise VpnError(f"inbound {inbound_id} not found")

        settings = _loads(inbound.get("settings", "{}"))
        if "clients" not in settings:
            raise VpnError("no clients in inbound")

        for client in settings["clients"]:
            if client.get("id") == client_uuid:
                # تمدید زمان
                if add_days > 0:
                    current_expiry = client.get("expiryTime", 0)
                    if current_expiry == 0:
                        # بدون انقضا - از الان حساب کن
                        current_expiry = int(time.time() * 1000)
                    
                    # اگر منقضی شده، از الان حساب کن
                    if current_expiry < int(time.time() * 1000):
                        current_expiry = int(time.time() * 1000)
                    
                    client["expiryTime"] = current_expiry + add_days * 86400000

                # افزودن حجم
                if add_traffic_mb > 0:
                    if reset_traffic:
                        client["totalGB"] = add_traffic_mb * MB
                    else:
                        current = client.get("totalGB", 0)
                        client["totalGB"] = current + add_traffic_mb * MB

                client["enable"] = True
                break
        else:
            raise VpnError(f"client {client_uuid} not found in inbound {inbound_id}")

        await self._request(
            "PUT",
            f"xui/inbound/{inbound_id}",
            json_body={
                "enable": inbound.get("enable", True),
                "up": inbound.get("up", 0),
                "down": inbound.get("down", 0),
                "total": inbound.get("total", 0),
                "remark": inbound.get("remark", ""),
                "listen": inbound.get("listen", ""),
                "stream": inbound.get("stream", ""),
                "settings": json.dumps(settings),
                "tag": inbound.get("tag", ""),
            },
        )

        logger.info("xui2 client extended: %s", email)

    async def get_client_usage(
        self, inbound_id: int, client_uuid: str
    ) -> UsageInfo:
        """دریافت مصرف کلاینت."""
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return UsageInfo(found=False)

        settings = _loads(inbound.get("settings", "{}"))
        if "clients" not in settings:
            return UsageInfo(found=False)

        for client in settings["clients"]:
            if client.get("id") == client_uuid:
                up = client.get("up", 0)
                down = client.get("down", 0)
                total = client.get("totalGB", 0)
                expiry = client.get("expiryTime", 0)
                
                return UsageInfo(
                    up=up,
                    down=down,
                    total=total,
                    expiry_ms=expiry,
                    enable=client.get("enable", True),
                )

        return UsageInfo(found=False)

    async def disable_client(self, inbound_id: int, client_uuid: str) -> None:
        """غیرفعال کردن کلاینت."""
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return

        settings = _loads(inbound.get("settings", "{}"))
        if "clients" not in settings:
            return

        for client in settings["clients"]:
            if client.get("id") == client_uuid:
                client["enable"] = False
                break

        await self._request(
            "PUT",
            f"xui/inbound/{inbound_id}",
            json_body={
                "enable": inbound.get("enable", True),
                "up": inbound.get("up", 0),
                "down": inbound.get("down", 0),
                "total": inbound.get("total", 0),
                "remark": inbound.get("remark", ""),
                "listen": inbound.get("listen", ""),
                "stream": inbound.get("stream", ""),
                "settings": json.dumps(settings),
                "tag": inbound.get("tag", ""),
            },
        )

    async def enable_client(self, inbound_id: int, client_uuid: str) -> None:
        """فعال کردن کلاینت."""
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return

        settings = _loads(inbound.get("settings", "{}"))
        if "clients" not in settings:
            return

        for client in settings["clients"]:
            if client.get("id") == client_uuid:
                client["enable"] = True
                break

        await self._request(
            "PUT",
            f"xui/inbound/{inbound_id}",
            json_body={
                "enable": inbound.get("enable", True),
                "up": inbound.get("up", 0),
                "down": inbound.get("down", 0),
                "total": inbound.get("total", 0),
                "remark": inbound.get("remark", ""),
                "listen": inbound.get("listen", ""),
                "stream": inbound.get("stream", ""),
                "settings": json.dumps(settings),
                "tag": inbound.get("tag", ""),
            },
        )