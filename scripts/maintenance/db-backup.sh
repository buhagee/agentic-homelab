#!/usr/bin/env bash
# =============================================================================
# scripts/maintenance/db-backup.sh — Qacey Platform database dumps
# =============================================================================
# Dumps all databases to /mnt/hdd1/qacey/db-backups/ before nightly backup.
# Run as root via systemd (qacey-db-backup.service) before qacey-backup.service.
# Manual run: sudo bash scripts/maintenance/db-backup.sh
# =============================================================================
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="/mnt/hdd1/qacey/db-backups"
DATE=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/qacey-db-backup.log"

# shellcheck source=scripts/lib/platform-env.sh
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
# shellcheck source=scripts/lib/alert.sh
source "${PLATFORM_DIR}/scripts/lib/alert.sh"

exec >> "$LOG_FILE" 2>&1
cleanup() {
  local rc=$?
  rm -f "$BACKUP_DIR"/*.sql.gz.tmp "$BACKUP_DIR"/*.sqlite3.gz.tmp 2>/dev/null || true
  if [[ $rc -ne 0 ]]; then
    send_alert \
      "Qacey DB backup failed" \
      "db-backup.sh failed with status $rc; see /var/log/qacey-db-backup.log." \
      || true
  fi
  exit $rc
}
trap cleanup EXIT

load_platform_env "$PLATFORM_DIR"
echo ""
echo "=== Database backup started: $(date '+%Y-%m-%dT%H:%M:%S%z') ==="

mkdir -p "$BACKUP_DIR"

dump_postgres() {
  local container="$1" user="$2" database="$3" out="$4"
  local tmp="${out}.tmp"

  if docker exec "$container" pg_dump -U "$user" "$database" | gzip > "$tmp"; then
    if [[ -s "$tmp" ]]; then
      mv "$tmp" "$out"
    else
      echo "ERROR: empty dump for $database"
      rm -f "$tmp"
      return 1
    fi
  else
    rm -f "$tmp"
    return 1
  fi
}

dump_sqlite() {
  local source="$1" out="$2"
  local tmp="${out}.tmp"

  if [[ ! -f "$source" ]]; then
    echo "ERROR: SQLite database not found: $source"
    return 1
  fi

  rm -f "$tmp" "${tmp}.gz"
  if python3 - "$source" "$tmp" <<'PY'
import sqlite3
import sys

source, target = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
dst = sqlite3.connect(target)
try:
    with dst:
        src.backup(dst)
finally:
    dst.close()
    src.close()
PY
  then
    gzip -f "$tmp"
    mv "${tmp}.gz" "$out"
  else
    rm -f "$tmp" "${tmp}.gz"
    return 1
  fi
}

echo "Backing up Immich database..."
dump_postgres immich-postgres immich immich "$BACKUP_DIR/immich_$DATE.sql.gz"

# Paperless currently runs on SQLite. The Postgres service is empty and unused.
echo "Backing up Paperless SQLite database..."
dump_sqlite "/mnt/ssd/qacey/paperless/data/db.sqlite3" \
  "$BACKUP_DIR/paperless_$DATE.sqlite3.gz"


echo "Cleaning up old backups (keeping last 7 days)..."
find "$BACKUP_DIR" -type f \( -name "*.sql.gz" -o -name "*.sqlite3.gz" \) -mtime +7 -delete

echo "=== Database backup finished: $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
echo "Backup size: $(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo 'N/A')"
