"""تست رگرسیون xui3 در برابر پنل واقعی.

هشدار: این تست روی پنل واقعی یک کلاینت موقت می‌سازد و در پایان پاکش می‌کند.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("BOT_TOKEN", "0:test")
os.environ.update(
    XUI_VARIANT="xui3",
    XUI_BASE_URL="https://138.199.216.221:50067",
    XUI_WEB_BASE_PATH="039i881dMbhx5VurVZ",
    XUI_API_TOKEN="bot_930f8f731c53df666f21a925a2b34e12aae8192ea365e5ee",
    XUI_NODE_HOST="138.199.216.221",
    XUI_SUB_BASE_URL="https://138.199.216.221:2096/c5q317obprv2q65r",
    XUI_VERIFY_SSL="false",
)

from app.services.vpn import get_provider  # noqa: E402

MB = 1024 ** 2
EMAIL = "bot-regression-test"
failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got} want={want}", flush=True)
    if not ok:
        failures.append(label)


async def main() -> None:
    p = get_provider()
    print("provider:", type(p).__name__, flush=True)

    print("\n[1] ping + ensure_share_addr")
    check("ping", await p.ping(), True)
    await p.ensure_share_addr()

    print("\n[2] create client (1GB / 30d / 2 devices)")
    res = await p.create_client(
        inbound_id=1,
        email=EMAIL,
        days=30,
        traffic_mb=1024,
        device_limit=2,
        telegram_id=123,
    )
    print("   uuid:", res.uuid, "| sub:", res.sub_link)
    print("   link:", res.config_link[:90])
    check("quota after create", (await p._get_client(EMAIL))["totalGB"], 1024 * MB)
    check("limitHwid mapped", (await p._get_client(EMAIL))["limitHwid"], 2)

    print("\n[3] link carries the node address")
    import base64, json

    raw = res.config_link.split("://", 1)[1]
    payload = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
    print("   add:", repr(payload.get("add")), "port:", payload.get("port"))
    check("link add == node host", payload.get("add"), "138.199.216.221")

    print("\n[4] set_quota_mb -> 2GB (expiry must survive)")
    await p.set_quota_mb(1, res.uuid, EMAIL, 2048)
    c = await p._get_client(EMAIL)
    check("quota resized", c["totalGB"], 2048 * MB)
    check("expiry survived quota change", c["expiryTime"] > int(time.time() * 1000), True)

    print("\n[5] extend_client +30d reset_traffic=True")
    before = (await p._get_client(EMAIL))["expiryTime"]
    await p.extend_client(1, res.uuid, EMAIL, 30, 512, reset_traffic=True)
    c = await p._get_client(EMAIL)
    check("expiry extended", c["expiryTime"] > before, True)
    check("quota reset to add amount", c["totalGB"], 512 * MB)

    print("\n[6] set_enabled False then True (quota must survive)")
    await p.set_enabled(1, res.uuid, EMAIL, False)
    c = await p._get_client(EMAIL)
    check("disabled", c["enable"], False)
    check("quota survived disable", c["totalGB"], 512 * MB)
    check("expiry survived disable", c["expiryTime"] > int(time.time() * 1000), True)
    await p.set_enabled(1, res.uuid, EMAIL, True)
    c = await p._get_client(EMAIL)
    check("re-enabled", c["enable"], True)
    check("quota survived re-enable", c["totalGB"], 512 * MB)

    print("\n[7] usage")
    usage = await p.get_usage(EMAIL)
    print("   found:", usage.found, "| total:", usage.total)
    allu = await p.get_all_usage()
    check("email present in bulk usage", EMAIL in allu, True)

    print("\n[8] build_client_link regenerates")
    check("link rebuilt", bool(await p.build_client_link(1, res.uuid, EMAIL)), True)

    print("\n[9] cleanup")
    await p.delete_client(1, EMAIL)
    try:
        await p._get_client(EMAIL)
        check("deleted", True, False)
    except Exception:
        check("deleted", True, True)

    await p.close()
    print("\n" + ("ALL PASSED" if not failures else f"FAILURES: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(asyncio.wait_for(main(), timeout=90)))