"""گزارش هماهنگی callback بین کیبورد و هندلرهای پنل."""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

p = open("app/handlers/admin/panels.py", encoding="utf-8").read()
k = open("app/keyboards/admin.py", encoding="utf-8").read()

handlers = set(re.findall(r"F\.action == \"(\w+)\"", p))
used = set(re.findall(r"action=\"(\w+)\"", k))
used |= set(re.findall(r'action=([A-Za-z_]+)\)', k))
used |= set(re.findall(r'_back\("(\w+)"', k))
used |= set(re.findall(r"action=([A-Za-z_]+), arg=", k))

# اکشن‌هایی که در بقیه هندلرها استفاده می‌شوند
other = open("app/handlers/admin/panel.py", encoding="utf-8").read()
handlers |= set(re.findall(r"F\.action == \"(\w+)\"", other))

print("HANDLERS   :", " ".join(sorted(handlers)))
print()
print("REFERENCED BUT MISSING (کلید دکمه بدون هندلر):")
for a in sorted(used - handlers):
    print("   ", a)
print()
print("HANDLED BUT NEVER SHOWN:")
for a in sorted(handlers - used):
    print("   ", a)
