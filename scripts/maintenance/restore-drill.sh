#!/usr/bin/env bash
# Restore the latest Vaultwarden data from B2 into a throwaway container.
# Production is not touched.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTAINER="qacey-vaultwarden-restore"
TMP_DIR="$(mktemp -d /tmp/qacey-restore-drill.XXXXXX)"

if [[ -n "${RESTORE_PORT:-}" ]]; then
  PORT="$RESTORE_PORT"
else
  PORT="$(
    python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
  )"
fi

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# shellcheck source=scripts/lib/platform-env.sh
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
load_platform_env "$PLATFORM_DIR"
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/versions.env"

for key in B2_ACCOUNT_ID B2_ACCOUNT_KEY B2_BUCKET RESTIC_PASSWORD VAULTWARDEN_VERSION; do
  [[ -n "${!key:-}" ]] || { echo "Missing $key" >&2; exit 1; }
done

export B2_ACCOUNT_ID B2_ACCOUNT_KEY
export RESTIC_REPOSITORY="b2:${B2_BUCKET}:/qacey"
export RESTIC_PASSWORD

echo "Restoring latest Vaultwarden data to $TMP_DIR"
restic restore latest --target "$TMP_DIR" --include /mnt/ssd/qacey/vaultwarden

DATA_DIR="${TMP_DIR}/mnt/ssd/qacey/vaultwarden"
[[ -f "${DATA_DIR}/db.sqlite3" ]] || { echo "Missing restored db.sqlite3" >&2; exit 1; }

python3 - "${DATA_DIR}/db.sqlite3" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
count = connection.execute("SELECT count(*) FROM users").fetchone()[0]
print(f"SQLite integrity: users={count}")
PY

docker run -d --rm --name "$CONTAINER" \
  --user 0 \
  -p "127.0.0.1:${PORT}:80" \
  -e "DOMAIN=http://127.0.0.1:${PORT}" \
  -e "SIGNUPS_ALLOWED=false" \
  -v "${DATA_DIR}:/data" \
  "vaultwarden/server:${VAULTWARDEN_VERSION}" >/dev/null

for _attempt in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/alive" >/dev/null 2>&1; then
    echo "Restore drill passed: Vaultwarden is serving from the restored data"
    exit 0
  fi
  sleep 1
done

echo "Restore drill failed: Vaultwarden did not become healthy" >&2
docker logs --tail 40 "$CONTAINER" >&2 || true
exit 1
