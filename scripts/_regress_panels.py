"""تست رگرسیون پنل/اینباند در برابر دیتابیس و پنل واقعی.

ساخت پنل → ثبت → تست اتصال → ساخت اینباند → خواندن → حذف اینباند
و بازگرداندن دیتابیس و پنل به وضعیت اولیه.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("BOT_TOKEN", "0:test")
os.environ.update(
    DATABASE_URL="sqlite+aiosqlite:///./data/panel_test.db",
    XUI_VARIANT="xui3",
    XUI_BASE_URL="https://138.199.216.221:50067",
    XUI_WEB_BASE_PATH="039i881dMbhx5VurVZ",
    XUI_API_TOKEN="bot_930f8f731c53df666f21a925a2b34e12aae8192ea365e5ee",
    XUI_NODE_HOST="138.199.216.221",
    XUI_SUB_BASE_URL="https://138.199.216.221:2096/c5q317obprv2q65r",
    XUI_VERIFY_SSL="false",
)

from app.db.models import Panel, PanelInbound  # noqa: E402
from app.db.session import dispose_db, get_sessionmaker, init_db  # noqa: E402
from app.services import panel_service as ps  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got} want={want}", flush=True)
    if not ok:
        failures.append(label)


async def main() -> None:
    await init_db()
    sm = get_sessionmaker()

    try:
        async with sm() as session:
            print("\n[1] seed .env panel")
            panel = await ps.ensure_default_from_env(session)
            check("panel seeded", panel is not None, True)
            if panel is None:
                return 1
            pid = panel.id

            # اگر قبلاً seed شده بود هم بگیریمش
            panel = await ps.get_panel(session, pid)
            print(f"   id={panel.id} title={panel.title!r} variant={panel.variant!r}")
            check("variant xui3", panel.variant, "xui3")
            check("token set", bool(panel.api_token), True)

            print("\n[2] list / re-seed is idempotent")
            panels = await ps.list_panels(session)
            check("one panel", len(panels) >= 1, True)
            again = await ps.ensure_default_from_env(session)
            check("no duplicate panel", again, None)

            print("\n[3] test connection")
            await ps.test_panel(session, panel)
            print("   OK")

            print("\n[4] create inbound via provider")
            client = ps.get_provider_for_panel(panel)
            options_before = await client.list_inbound_options()
            print("   inbounds before:", len(options_before))
            inbound_id = await client.create_inbound(
                {
                    "protocol": "vless",
                    "network": "tcp",
                    "security": "none",
                    "port": 44401,
                    "remark": "bot-test-inbound",
                }
            )
            check("inbound id returned", inbound_id > 0, True)
            print("   created id:", inbound_id)

            print("\n[5] register inbound in bot")
            row = await ps.register_inbound(
                session,
                panel,
                inbound_id=inbound_id,
                remark="bot-test-inbound",
                protocol="vless",
                port=44401,
                network="tcp",
                security="none",
            )
            check("registered", row is not None, True)
            check("row count", len(await ps.list_inbounds_of(session, pid)), 1)

            print("\n[6] duplicate registration is rejected")
            dupe = await ps.register_inbound(session, panel, inbound_id=inbound_id)
            check("dupe returns None", dupe, None)

            print("\n[7] sync metadata from live panel")
            await ps.sync_inbound_meta(session, row)
            print(f"   protocol={row.protocol} port={row.port} net={row.network}")
            check("protocol synced", row.protocol, "vless")
            check("port synced", row.port, 44401)

            print("\n[8] unregister (bot only)")
            await ps.unregister_inbound(session, row)
            check("unregistered", len(await ps.list_inbounds_of(session, pid)), 0)
            opts = await client.list_inbound_options()
            check("still on panel", inbound_id in [o["id"] for o in opts], True)

            print("\n[9] delete inbound from panel (cleanup)")
            await client.delete_inbound(inbound_id)
            opts = await client.list_inbound_options()
            check(
                "removed from panel",
                inbound_id in [o["id"] for o in opts],
                False,
            )

            print("\n[10] update panel field")
            p2 = await ps.update_panel(session, panel, title="پنل تست")
            check("title changed", p2.title, "پنل تست")
            await ps.update_panel(session, p2, title=panel.title)

            print("\n[11] cache invalidation")
            ps.invalidate_cache(pid)
            c1 = ps.get_provider_for_panel(panel)
            c2 = ps.get_provider_for_panel(panel)
            check("cache rebuilt", c1 is c2, True)

            await ps.close_all()

        # پاک‌سازی دیتابیس تست
        await dispose_db()
        for path in ("data/panel_test.db",):
            try:
                os.remove(path)
            except OSError:
                pass
        print("\n   (test db removed)")
    finally:
        try:
            await dispose_db()
        except Exception:  # noqa: BLE001
            pass

    print("\n" + ("ALL PASSED" if not failures else f"FAILURES: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
