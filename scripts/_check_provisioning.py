"""آزمون منطق resolve_inbounds و تگ پنل (بدون دسترسی شبکه/دیتابیس)."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app.services.provisioning import _panel_tag, panel_id_from_email

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


print("[email -> panel tag]")
check("old email (no tag)", panel_id_from_email("123-srv-ab12cd-i4"), None)
check("old email trial", panel_id_from_email("123-trial-ff00aa-i1"), None)
check("new email panel 3", panel_id_from_email("123-srv-ab12cd-p3-i4"), 3)
check("new email panel 12", panel_id_from_email("123-srv-ab12cd-p12-i4"), 12)
check("tag after inbound", panel_id_from_email("123-srv-ab12cd-i4-p7"), 7)
check("empty", panel_id_from_email(""), None)
check("None-safe", panel_id_from_email(None), None)

print("[_panel_tag]")
check("default panel", _panel_tag(None), "")
check("panel 3", _panel_tag(3), "-p3")

print("[resolve_inbounds parsing]")
import app.services.provisioning as prov
from app.services.provisioning import resolve_inbounds


class FakeCfg:
    def __init__(self, value):
        self.value = value

    async def get(self, session, key, default=""):
        return self.value


async def parse(raw):
    fake = FakeCfg(raw)
    orig = prov.cfg
    prov.cfg = fake
    try:
        return await prov.resolve_inbounds(None, 9)
    finally:
        prov.cfg = orig


async def main():
    check("legacy '4,6'", await parse("4,6"), [(None, 4), (None, 6)])
    check("legacy spaces", await parse(" 4 , 6 "), [(None, 4), (None, 6)])
    check("multi-panel '1:4,2:6'", await parse("1:4,2:6"), [(1, 4), (2, 6)])
    check("mixed '4,2:6'", await parse("4,2:6"), [(None, 4), (2, 6)])
    check("dupes collapsed", await parse("4,4"), [(None, 4)])
    check("junk dropped", await parse("abc,-5,,7"), [(None, 7)])
    check("empty -> fallback", await parse(""), [(None, 9)])
    check("bad-only -> fallback", await parse(",,xyz"), [(None, 9)])

    # ---- admin-side parser: roundtrip with provisioning ----
    print("[admin _parse_multi / _format_multi roundtrip]")
    from app.handlers.admin.panel import _format_multi, _parse_multi

    cases = [
        ("4,6", [(None, 4), (None, 6)]),
        ("1:4,2:6", [(1, 4), (2, 6)]),
        ("4,2:6", [(None, 4), (2, 6)]),
        ("", []),
        ("abc,-5,,7", [(None, 7)]),
    ]
    for raw, want in cases:
        got = _parse_multi(raw)
        check(f"parse {raw!r}", got, want)
        rt = _parse_multi(_format_multi(got))
        check(f"roundtrip {raw!r}", rt, got)

    # provisioning sees exactly what admin writes (non-empty only:
    # provisioning adds a fallback when the setting is empty by design)
    for raw, want in cases:
        if not want:
            continue
        p_res = await parse(raw)
        a_res = _parse_multi(raw)
        check(f"agree on {raw!r}", a_res, p_res)

    # empty setting: admin shows [], provisioning falls back to package inbound
    check("empty -> admin []", _parse_multi(""), [])
    check("empty -> provisioning fallback", await parse(""), [(None, 9)])

    # ---- picker keyboard renders ----
    print("[picker keyboard]")
    from app.keyboards.admin import multi_inbound_picker

    entries = [
        (1, "پنل اولیه", 4, "", "vmess", 18677),
        (2, "سرور آلمان", 6, "reality", "vless", 443),
    ]
    kb1 = multi_inbound_picker(entries, {(1, 4)}, True)
    rows1 = [row for row in kb1.inline_keyboard]
    check("2 entries + manual + back", len(rows1), 4)
    check("each row single button", all(len(r) == 1 for r in rows1), True)
    check("first marked selected", rows1[0][0].text.startswith("✅"), True)
    check("second unmarked", rows1[1][0].text.startswith("⬜️"), True)

    kb2 = multi_inbound_picker([], set(), False)
    check("empty shows hint + manual + back", len(kb2.inline_keyboard), 3)

    # callback payloads must roundtrip through AdminCB
    from app.keyboards.admin import AdminCB

    cb = AdminCB(action="multi_toggle", arg=2, arg2=6)
    parsed = AdminCB.unpack(cb.pack())
    check("cb arg roundtrip", (parsed.arg, parsed.arg2), (2, 6))
    cb0 = AdminCB(action="multi_toggle", arg=0, arg2=4)
    p0 = AdminCB.unpack(cb0.pack())
    check("cb arg 0 -> None", p0.arg or None, None)


asyncio.run(main())

print("\n" + ("ALL PASSED" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
