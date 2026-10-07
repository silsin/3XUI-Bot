#!/bin/bash
# =============================================================================
# transfer-import.sh  —  Install the bot on the DESTINATION server
# =============================================================================
# Usage:
#   bash transfer-import.sh /path/to/alovpn_transfer_YYYYMMDD_HHMMSS.tar.gz
#
# What it does:
#   1. Extracts the archive
#   2. Clones / pulls the latest bot code (or uses existing project dir)
#   3. Restores the .env
#   4. Restores the database into a fresh Docker volume
#   5. Optionally restores backups/
#   6. Builds and starts the bot
#   7. Runs a health-check to confirm the container is alive
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] ✔ ${NC}$1"; }
info() { echo -e "${CYAN}[$(date +'%Y-%m-%d %H:%M:%S')] ℹ ${NC}$1"; }
warn() { echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] ⚠ ${NC}$1"; }
err()  { echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ✖ ERROR: ${NC}$1" >&2; exit 1; }

# ── argument check ────────────────────────────────────────────────────────────
ARCHIVE="${1:-}"
[[ -n "$ARCHIVE" ]] || err "Usage: $0 /path/to/transfer_archive.tar.gz"
[[ -f "$ARCHIVE" ]] || err "Archive not found: $ARCHIVE"

# ── configurable install location ─────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-/opt/alovpnBot}"
REPO_URL="${REPO_URL:-}"          # set to your git repo URL, or leave empty to skip git clone

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGING_DIR"' EXIT

# ── 1. extract archive ────────────────────────────────────────────────────────
info "Extracting archive…"
tar -xzf "$ARCHIVE" -C "$STAGING_DIR"
log "Extracted to $STAGING_DIR"

# read metadata
META_FILE="$STAGING_DIR/meta/transfer.json"
SOURCE_VOLUME=""
EXPORTED_AT=""
if [[ -f "$META_FILE" ]]; then
    # simple grep-based JSON parsing (no jq required)
    SOURCE_VOLUME=$(grep '"docker_volume"' "$META_FILE" | sed 's/.*: *"\(.*\)".*/\1/')
    EXPORTED_AT=$(grep '"exported_at"'   "$META_FILE" | sed 's/.*: *"\(.*\)".*/\1/')
    info "Transfer archive from: $EXPORTED_AT"
    info "Original volume name : $SOURCE_VOLUME"
fi

DEST_VOLUME="alovpn-bot_bot_data"

# ── 2. ensure project code is present ─────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Project already exists at $INSTALL_DIR — pulling latest code…"
    git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed — continuing with existing code."
elif [[ -n "$REPO_URL" ]]; then
    info "Cloning repo from $REPO_URL into $INSTALL_DIR…"
    git clone "$REPO_URL" "$INSTALL_DIR"
else
    warn "REPO_URL is not set and $INSTALL_DIR does not have .git."
    warn "Please manually place the project code at $INSTALL_DIR before running this script."
    warn "Continuing — will restore database and .env only."
    mkdir -p "$INSTALL_DIR"
fi

# ── 3. stop any existing bot container ────────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^alovpn-bot$"; then
    info "Stopping existing container alovpn-bot…"
    docker stop alovpn-bot 2>/dev/null || true
    docker rm   alovpn-bot 2>/dev/null || true
fi

# ── 4. restore .env ───────────────────────────────────────────────────────────
info "Restoring .env…"
if [[ -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env" "$INSTALL_DIR/.env.bak.$(date +%Y%m%d_%H%M%S)"
    warn "Existing .env backed up."
fi
cp "$STAGING_DIR/.env" "$INSTALL_DIR/.env"
log ".env restored."

# ── 5. restore database into Docker volume ────────────────────────────────────
info "Restoring database into volume '$DEST_VOLUME'…"

# Make sure the volume exists
docker volume create "$DEST_VOLUME" >/dev/null 2>&1 || true

# Copy db files into the volume via a temporary container
DB_SRC="$STAGING_DIR/data"
docker run --rm \
    -v "$DB_SRC:/src:ro" \
    -v "${DEST_VOLUME}:/dst" \
    alpine:latest \
    sh -c "cp /src/*.db /dst/ 2>/dev/null && chown -R 0:0 /dst && chmod 644 /dst/*.db"
log "Database restored to volume."

# ── 6. restore backups (optional) ─────────────────────────────────────────────
if [[ -d "$STAGING_DIR/backups" ]]; then
    info "Restoring backups/…"
    mkdir -p "$INSTALL_DIR/backups"
    cp -rn "$STAGING_DIR/backups/." "$INSTALL_DIR/backups/"
    log "Backups restored ($(ls "$INSTALL_DIR/backups" | wc -l) files)."
fi

# ── 7. build and start ────────────────────────────────────────────────────────
info "Building and starting the bot…"
cd "$INSTALL_DIR"
docker compose pull  2>/dev/null || true
docker compose build --no-cache
docker compose up -d

log "Bot started."

# ── 8. health check ───────────────────────────────────────────────────────────
info "Waiting for container to become healthy…"
MAX_WAIT=60
WAITED=0
while [[ $WAITED -lt $MAX_WAIT ]]; do
    STATUS=$(docker inspect --format '{{.State.Status}}' alovpn-bot 2>/dev/null || echo "missing")
    if [[ "$STATUS" == "running" ]]; then
        break
    fi
    sleep 2
    WAITED=$((WAITED+2))
done

if [[ "$STATUS" == "running" ]]; then
    log "Container is running ✔"
    docker logs --tail 20 alovpn-bot
else
    err "Container did not reach 'running' state within ${MAX_WAIT}s. Check: docker logs alovpn-bot"
fi

# ── 9. next steps ─────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} Import complete!${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo ""
echo "  Verify the bot is working, then disable the SOURCE server:"
echo ""
echo -e "    ${YELLOW}# On the source server:${NC}"
echo -e "    ${YELLOW}bash scripts/transfer-disable-source.sh${NC}"
echo ""
echo "  To monitor this bot:"
echo -e "    ${YELLOW}docker logs -f alovpn-bot${NC}"
echo ""
