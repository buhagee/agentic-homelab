#!/usr/bin/env bash
# Restore the newest Paperless SQLite dump into a temporary directory.
# Production Paperless and its data are not touched.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="/mnt/hdd1/qacey/db-backups"
TMP_DIR="$(mktemp -d /tmp/qacey-paperless-restore.XXXXXX)"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

[[ "${EUID}" -eq 0 ]] || { echo "Run as root (sudo)" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

DUMP="$({
  find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'paperless_*.sqlite3.gz' \
    -printf '%T@ %p\n' 2>/dev/null || true
} | sort -nr | head -n 1 | cut -d' ' -f2-)"
[[ -n "${DUMP}" ]] || {
  echo "No Paperless SQLite dump found in ${BACKUP_DIR}" >&2
  exit 1
}

echo "Paperless restore drill"
echo "Dump: ${DUMP} ($(du -h "${DUMP}" | cut -f1))"

gzip -t "${DUMP}"
gunzip -c "${DUMP}" > "${TMP_DIR}/db.sqlite3"

python3 - "${TMP_DIR}/db.sqlite3" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    integrity = connection.execute("PRAGMA integrity_check;").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"SQLite integrity check failed: {integrity}")
    count = connection.execute("SELECT count(*) FROM documents_document;").fetchone()[0]
    tables = connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table';"
    ).fetchone()[0]
finally:
    connection.close()

print(f"Paperless SQLite integrity: {integrity}")
print(f"Paperless tables restored: {tables}")
print(f"Paperless documents restored: {count}")
PY

media_root="/mnt/hdd2/qacey/ssd-mirror/paperless/media"
if [[ -d "${media_root}" ]]; then
  sample="$(find "${media_root}" -type f ! -name '*.lock' -print -quit 2>/dev/null || true)"
  if [[ -n "${sample}" ]]; then
    echo "Media mirror sample: ${sample}"
  else
    echo "WARN: media mirror exists but no non-lock sample was found" >&2
  fi
else
  echo "WARN: media mirror not found at ${media_root}" >&2
fi

echo "Paperless restore drill passed. Production was not touched."
