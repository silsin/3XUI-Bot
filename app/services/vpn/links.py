"""ساخت لینک اتصال از اطلاعات inbound پنل."""

from __future__ import annotations

import base64
import json
from urllib.parse import quote, urlencode


def _stream_params(stream: dict) -> dict[str, str]:
    """پارامترهای مشترک transport/security را از streamSettings استخراج می‌کند."""
    params: dict[str, str] = {}
    network = stream.get("network", "tcp")
    security = stream.get("security", "none")
    params["type"] = network
    params["security"] = security

    if security == "reality":
        reality = stream.get("realitySettings", {}) or {}
        rs = reality.get("settings", {}) or {}
        server_names = reality.get("serverNames") or []
        short_ids = reality.get("shortIds") or []
        if server_names:
            params["sni"] = server_names[0]
        if short_ids:
            params["sid"] = short_ids[0]
        if rs.get("publicKey"):
            params["pbk"] = rs["publicKey"]
        if rs.get("fingerprint"):
            params["fp"] = rs["fingerprint"]
        if rs.get("spiderX"):
            params["spx"] = rs["spiderX"]
    elif security in {"tls", "xtls"}:
        tls = stream.get("tlsSettings", {}) or {}
        settings = tls.get("settings", {}) or {}
        if tls.get("serverName"):
            params["sni"] = tls["serverName"]
        if settings.get("fingerprint"):
            params["fp"] = settings["fingerprint"]
        alpn = tls.get("alpn") or []
        if alpn:
            params["alpn"] = ",".join(alpn)

    if network == "ws":
        ws = stream.get("wsSettings", {}) or {}
        if ws.get("path"):
            params["path"] = ws["path"]
        host = (ws.get("headers") or {}).get("Host") or ws.get("host")
        if host:
            params["host"] = host
    elif network == "grpc":
        grpc = stream.get("grpcSettings", {}) or {}
        if grpc.get("serviceName"):
            params["serviceName"] = grpc["serviceName"]
        if grpc.get("multiMode"):
            params["mode"] = "multi"
    elif network in {"tcp", "raw"}:
        tcp = stream.get("tcpSettings", {}) or {}
        header = (tcp.get("header") or {}).get("type")
        if header and header != "none":
            params["headerType"] = header
            request = (tcp.get("header") or {}).get("request") or {}
            paths = request.get("path") or []
            hosts = (request.get("headers") or {}).get("Host") or []
            if paths:
                params["path"] = paths[0]
            if hosts:
                params["host"] = hosts[0] if isinstance(hosts, list) else hosts
    elif network == "httpupgrade":
        hu = stream.get("httpupgradeSettings", {}) or {}
        if hu.get("path"):
            params["path"] = hu["path"]
        if hu.get("host"):
            params["host"] = hu["host"]
    elif network in {"xhttp", "splithttp"}:
        xh = stream.get("xhttpSettings", {}) or stream.get("splithttpSettings", {}) or {}
        if xh.get("path"):
            params["path"] = xh["path"]
        if xh.get("host"):
            params["host"] = xh["host"]
        if xh.get("mode"):
            params["mode"] = xh["mode"]

    return {k: v for k, v in params.items() if v not in (None, "")}


def build_link(
    *,
    protocol: str,
    host: str,
    port: int,
    client: dict,
    stream: dict,
    remark: str,
) -> str:
    """لینک اتصال نهایی برای کلاینت می‌سازد."""
    protocol = (protocol or "vless").lower()
    fragment = quote(remark, safe="")

    if protocol == "vless":
        params = _stream_params(stream)
        flow = client.get("flow")
        if flow:
            params["flow"] = flow
        query = urlencode(params, safe="/+")
        return f"vless://{client['id']}@{host}:{port}?{query}#{fragment}"

    if protocol == "trojan":
        params = _stream_params(stream)
        query = urlencode(params, safe="/+")
        password = client.get("password") or client.get("id")
        return f"trojan://{password}@{host}:{port}?{query}#{fragment}"

    if protocol == "vmess":
        stream_params = _stream_params(stream)
        payload = {
            "v": "2",
            "ps": remark,
            "add": host,
            "port": str(port),
            "id": client["id"],
            "aid": str(client.get("alterId", 0)),
            "scy": client.get("security", "auto"),
            "net": stream_params.get("type", "tcp"),
            "type": stream_params.get("headerType", "none"),
            "host": stream_params.get("host", ""),
            "path": stream_params.get("path", ""),
            "tls": stream_params.get("security", "none"),
            "sni": stream_params.get("sni", ""),
            "alpn": stream_params.get("alpn", ""),
            "fp": stream_params.get("fp", ""),
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        encoded = base64.b64encode(raw.encode()).decode()
        return f"vmess://{encoded}"

    if protocol == "shadowsocks":
        method = client.get("method", "aes-256-gcm")
        password = client.get("password", "")
        userinfo = base64.urlsafe_b64encode(
            f"{method}:{password}".encode()
        ).decode().rstrip("=")
        return f"ss://{userinfo}@{host}:{port}#{fragment}"

    # پروتکل ناشناخته - حداقل یک لینک قابل استفاده برگردان
    return f"{protocol}://{client.get('id', '')}@{host}:{port}#{fragment}"
