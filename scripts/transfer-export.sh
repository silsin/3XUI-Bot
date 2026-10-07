#!/bin/bash
# =============================================================================
# transfer-export.sh  —  Export everything from the SOURCE server
# =============================================================================
# Usage:
#   bash transfer-export.sh [--output /path/to/export.tar.gz]
#
# What it bundles:
#   - bot.db  (SQLite database, hot-copied via .dump)
#   - .env    (all environment variables)
#   - backups/ directory  (optional, existing backup files)
#   - docker volumes metadata (volume name recorded)
#
# The output is a single .tar.gz that transfer-import.sh consumes on the
# destination server.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] ✔ ${NC}$1"; }
info() { echo -e "${CYAN}[$(date +'%Y-%m-%d %H:%M:%S')] ℹ ${NC}$1"; }
warn() { echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] ⚠ ${NC}$1"; }
err()  { echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ✖ ERROR: ${NC}$1" >&2; exit 1; }

# ── defaults ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="${1:---output}"

if [[ "$OUTPUT_FILE" == "--output" ]]; then
    OUTPUT_FILE="/tmp/alovpn_transfer_$(date +%Y%m%d_%H%M%S).tar.gz"
fi
if [[ "$1" == "--output" && -n "${2:-}" ]]; then
    OUTPUT_FILE="$2"
fi

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGING_DIR"' EXIT

# ── locate .env ───────────────────────────────────────────────────────────────
ENV_FILE="$PROJECT_DIR/.env"
[[ -f "$ENV_FILE" ]] || err ".env not found at $PROJECT_DIR/.env — run from project root or check path."

# ── locate docker volume ──────────────────────────────────────────────────────
VOLUME_NAME="alovpn-bot_bot_data"
# try to auto-detect by inspecting running container
if docker inspect alovpn-bot &>/dev/null 2>&1; then
    VOLUME_NAME=$(docker inspect alovpn-bot \
        --format '{{ range .Mounts }}{{ if eq .Type "volume" }}{{ .Name }}{{ end }}{{ end }}' \
        2>/dev/null | head -1 || echo "alovpn-bot_bot_data")
fi

info "Project dir : $PROJECT_DIR"
info "Docker volume: $VOLUME_NAME"
info "Output file  : $OUTPUT_FILE"

mkdir -p "$STAGING_DIR/data" "$STAGING_DIR/meta"

# ── 1. stop bot gracefully (prevents SQLite write-ahead log corruption) ────────
info "Stopping bot container for a clean database snapshot…"
if docker ps --format '{{.Names}}' | grep -q "^alovpn-bot$"; then
    docker stop alovpn-bot
    RESTART_BOT=true
else
    warn "Container 'alovpn-bot' is not running — exporting live files."
    RESTART_BOT=false
fi

# ── 2. dump SQLite database ────────────────────────────────────────────────────
info "Exporting database…"

# Try to pull from named Docker volume first
if docker volume inspect "$VOLUME_NAME" &>/dev/null 2>&1; then
    docker run --rm \
        -v "${VOLUME_NAME}:/src:ro" \
        -v "${STAGING_DIR}/data:/dst" \
        alpine:latest \
        sh -c "cp /src/bot.db /dst/bot.db 2>/dev/null || true; cp /src/*.db /dst/ 2>/dev/null || true"
    log "Database copied from Docker volume."
elif [[ -f "$PROJECT_DIR/data/bot.db" ]]; then
    cp "$PROJECT_DIR/data/bot.db" "$STAGING_DIR/data/bot.db"
    log "Database copied from local data/ directory."
else
    err "Cannot locate bot.db — neither in Docker volume '$VOLUME_NAME' nor in $PROJECT_DIR/data/"
fi

# ── 3. copy .env ───────────────────────────────────────────────────────────────
info "Copying .env…"
cp "$ENV_FILE" "$STAGING_DIR/.env"

# ── 4. copy backups (optional) ────────────────────────────────────────────────
if [[ -d "$PROJECT_DIR/backups" ]]; then
    info "Including existing backups/…"
    cp -r "$PROJECT_DIR/backups" "$STAGING_DIR/backups"
fi

# ── 5. record metadata ────────────────────────────────────────────────────────
info "Recording metadata…"
cat > "$STAGING_DIR/meta/transfer.json" <<EOF
{
  "exported_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "hostname": "$(hostname)",
  "docker_volume": "$VOLUME_NAME",
  "project_dir": "$PROJECT_DIR",
  "bot_container": "alovpn-bot",
  "schema_version": "1"
}
EOF

# ── 6. create archive ─────────────────────────────────────────────────────────
info "Creating archive…"
tar -czf "$OUTPUT_FILE" -C "$STAGING_DIR" .
SIZE=$(du -sh "$OUTPUT_FILE" | cut -f1)
log "Archive created: $OUTPUT_FILE ($SIZE)"

# ── 7. restart bot on source (still disabled after transfer by transfer-import) ─
if [[ "$RESTART_BOT" == "true" ]]; then
    warn "Restarting source bot — remember to STOP it after confirming destination works."
    docker start alovpn-bot
fi

# ── 8. print next steps ───────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} Export complete!${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo ""
echo "  Transfer the archive to the destination server:"
echo ""
echo -e "    ${YELLOW}scp $OUTPUT_FILE user@DEST_SERVER:/opt/alovpnBot/${NC}"
echo ""
echo "  Then on the destination server run:"
echo ""
echo -e "    ${YELLOW}bash scripts/transfer-import.sh $OUTPUT_FILE${NC}"
echo ""
echo "  After verifying the destination is working, disable the source:"
echo ""
echo -e "    ${YELLOW}bash scripts/transfer-disable-source.sh${NC}"
echo ""
