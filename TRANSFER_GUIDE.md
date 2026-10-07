# Bot Server Transfer Guide

Move the entire bot — database, config, backups — from one server to another and shut down the old one.

---

## What gets transferred

| Item | How |
|------|-----|
| `bot.db` SQLite database | Copied from Docker named volume |
| `.env` configuration | Copied verbatim |
| `backups/` directory | Copied if present |
| Bot code | Pulled from Git on the destination (or cloned fresh) |

---

## Method A — Fully automated (from your Windows machine)

This uses `transfer-orchestrate.ps1` to SSH into both servers and do everything for you.

### Prerequisites
- OpenSSH client on Windows (built-in on Win 10/11)
- SSH key access to both servers
- The bot project code in a Git repo (optional but recommended)

### Run

```powershell
.\scripts\transfer-orchestrate.ps1 `
    -Source "root@OLD_SERVER_IP" `
    -Dest   "root@NEW_SERVER_IP" `
    -SourceProjectDir "/opt/alovpnBot" `
    -DestProjectDir   "/opt/alovpnBot" `
    -DestRepoUrl      "https://github.com/yourname/alovpnBot.git"
```

With a specific SSH key:
```powershell
.\scripts\transfer-orchestrate.ps1 `
    -Source "root@OLD_SERVER_IP" `
    -Dest   "root@NEW_SERVER_IP" `
    -SshKeyFile "~/.ssh/id_rsa"
```

The script will:
1. Upload transfer scripts to source
2. Run export on source → creates `/tmp/alovpn_transfer_DATE.tar.gz`
3. Download the archive to your machine, upload to destination
4. Run import on destination (git clone + restore DB + restore .env + docker compose up)
5. Show you the container status
6. Ask you to confirm before disabling the source

---

## Method B — Manual (SSH into each server yourself)

### Step 1 — Export from the source server

SSH into the source server, then:

```bash
cd /opt/alovpnBot
git pull   # make sure scripts are up to date

bash scripts/transfer-export.sh
# or specify output path:
bash scripts/transfer-export.sh --output /tmp/my_transfer.tar.gz
```

The script:
- Stops the bot cleanly (prevents SQLite WAL corruption)
- Dumps the database from the Docker volume
- Packages `.env` and `backups/`
- Restarts the source bot temporarily (while you verify destination)

### Step 2 — Copy the archive to the destination

```bash
# From source server
scp /tmp/alovpn_transfer_*.tar.gz root@NEW_SERVER_IP:/tmp/

# Or from your local machine
scp root@OLD_SERVER_IP:/tmp/alovpn_transfer_*.tar.gz root@NEW_SERVER_IP:/tmp/
```

### Step 3 — Import on the destination server

SSH into the destination server, then:

```bash
# Clone the bot code (first time only)
git clone https://github.com/yourname/alovpnBot.git /opt/alovpnBot

# Run the import
INSTALL_DIR=/opt/alovpnBot bash /opt/alovpnBot/scripts/transfer-import.sh /tmp/alovpn_transfer_*.tar.gz
```

The script:
- Restores `.env` (backs up any existing one)
- Creates the Docker volume and restores `bot.db` into it
- Restores `backups/`
- Runs `docker compose build && docker compose up -d`
- Health-checks that the container is running
- Prints the last 20 log lines

### Step 4 — Verify the destination

```bash
docker logs -f alovpn-bot
```

Test the bot in Telegram. Check that:
- `/start` works
- User data is intact
- VPN panel connectivity works

### Step 5 — Disable the source server

Once you are confident, SSH into the **source** server and run:

```bash
bash /opt/alovpnBot/scripts/transfer-disable-source.sh
```

This:
- Stops and removes both containers
- Creates `docker-compose.override.yml` that sets `restart: "no"` so they won't start on reboot
- Creates a `DISABLED` sentinel file
- Optionally deletes the Docker volume (you'll be prompted)

---

## Troubleshooting

### Container not running after import

```bash
docker logs alovpn-bot       # check startup errors
docker compose logs           # all services
```

Common causes:
- `.env` has wrong `BOT_TOKEN` — edit `/opt/alovpnBot/.env` and restart
- Port conflict — check `SUB_PORT` in `.env`
- Missing TLS certs — ensure `/root/cert` exists on the new server

### Database looks empty

The import copies the database from the archive. If the source export ran while the bot was under heavy write load, the WAL file may not have been checkpointed.

Fix: on the source server before exporting, run:
```bash
docker exec alovpn-bot python -c "
import asyncio, aiosqlite
async def wal():
    async with aiosqlite.connect('/app/data/bot.db') as db:
        await db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
asyncio.run(wal())
"
```
Then re-run the export.

### SCP transfer is slow

Use compression:
```bash
scp -C /tmp/alovpn_transfer_*.tar.gz root@NEW_SERVER_IP:/tmp/
```

Or use `rsync`:
```bash
rsync -avz --progress /tmp/alovpn_transfer_*.tar.gz root@NEW_SERVER_IP:/tmp/
```

### Want to do a dry-run (no stop)

Set `RESTART_BOT=false` in the export script or run it when the bot is already stopped:
```bash
docker stop alovpn-bot
bash scripts/transfer-export.sh
# Do NOT restart source until import is verified
```

---

## File reference

| Script | Where to run | Purpose |
|--------|-------------|---------|
| `scripts/transfer-export.sh` | Source server | Package DB + config into archive |
| `scripts/transfer-import.sh` | Destination server | Restore archive, build, start bot |
| `scripts/transfer-disable-source.sh` | Source server | Permanently disable source instance |
| `scripts/transfer-orchestrate.ps1` | Your Windows PC | Automate all steps via SSH |
