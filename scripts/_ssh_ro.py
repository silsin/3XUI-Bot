"""SSH read-only inspection of the target server.

Writes nothing to the remote host. Prints deployment layout only.
"""
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST, USER, PWD = "138.199.216.221", "root", "13740519ff"

CMDS = [
    "ls -la / | head -30",
    "ls -la /opt /srv /root 2>/dev/null | head -40",
    "find / -maxdepth 4 -name 'bot.py' -o -maxdepth 4 -name 'docker-compose.yml' 2>/dev/null | head -20",
    "docker ps -a 2>/dev/null || echo 'no docker'",
    "ls -la /root/cert 2>/dev/null",
    "df -h / | tail -2",
]


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PWD, timeout=15, banner_timeout=30)
    for cmd in CMDS:
        _, out, _ = c.exec_command(cmd, timeout=40)
        data = out.read().decode("utf-8", "replace")
        print(f"$ {cmd}\n{data}")
        print("-" * 60)
    c.close()


if __name__ == "__main__":
    main()