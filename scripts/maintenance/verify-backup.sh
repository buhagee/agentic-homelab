#!/usr/bin/env bash
# Verify the offsite restic repository is recent and readable.
# Runs daily from qacey-backup-verify.timer after the nightly backup.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="/var/log/qacey-backup-verify.log"
MAX_AGE_HOURS=24
DRY_RUN=0
ALERT_SENT=0

# shellcheck source=scripts/lib/platform-env.sh
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
# shellcheck source=scripts/lib/alert.sh
source "${PLATFORM_DIR}/scripts/lib/alert.sh"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "Usage: $0 [--dry-run]" >&2
      exit 2
      ;;
  esac
done

fail() {
  local subject="$1"
  local body="$2"
  send_alert "$subject" "$body" || true
  ALERT_SENT=1
  exit 1
}

trap 'if [[ ${ALERT_SENT:-0} -eq 0 ]]; then send_alert "Qacey backup verification failed" "Unexpected error. See ${LOG_FILE}." || true; fi' ERR

exec >> "${LOG_FILE}" 2>&1
echo ""
echo "=== Qacey backup verification started: $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
[[ ${DRY_RUN} -eq 1 ]] && echo "[DRY RUN MODE]"

load_platform_env "${PLATFORM_DIR}" || fail \
  "Qacey backup verification failed" \
  "Could not load the platform environment files."

missing=()
for key in B2_ACCOUNT_ID B2_ACCOUNT_KEY B2_BUCKET RESTIC_PASSWORD; do
  [[ -n "${!key:-}" ]] || missing+=("${key}")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  fail "Qacey backup verification failed" \
    "Missing offsite settings: ${missing[*]}. See ${LOG_FILE}."
fi

command -v restic >/dev/null 2>&1 || fail \
  "Qacey backup verification failed" \
  "restic is not installed on the host."

export B2_ACCOUNT_ID B2_ACCOUNT_KEY
export RESTIC_REPOSITORY="b2:${B2_BUCKET}:/qacey"
export RESTIC_PASSWORD

snapshots_json="$(restic snapshots --json --latest 1 2>/dev/null)" || fail \
  "Qacey backup verification failed" \
  "Could not read the restic repository. See ${LOG_FILE}."

latest_epoch="$(printf '%s' "${snapshots_json}" | python3 -c '
import datetime
import json
import re
import sys

data = json.load(sys.stdin)
if not data:
    raise SystemExit(2)
stamp = re.sub(r"\.\d+", "", data[-1]["time"]).replace("Z", "+00:00")
print(int(datetime.datetime.fromisoformat(stamp).timestamp()))
')" || fail \
  "Qacey backup verification failed" \
  "No restic snapshots were found. See ${LOG_FILE}."

now="$(date +%s)"
age_seconds=$(( now - latest_epoch ))
(( age_seconds < 0 )) && age_seconds=0
age_hours=$(( age_seconds / 3600 ))
echo "Latest snapshot age: ${age_hours}h (limit ${MAX_AGE_HOURS}h)."

if (( age_hours > MAX_AGE_HOURS )); then
  fail "Qacey backup verification failed" \
    "Latest restic snapshot is ${age_hours}h old; limit is ${MAX_AGE_HOURS}h. Check the nightly backup."
fi

if [[ ${DRY_RUN} -eq 0 ]]; then
  echo "Running sampled repository integrity check (1/50 data subset)..."
  restic check --read-data-subset=1/50 || fail \
    "Qacey backup verification failed" \
    "restic check failed. See ${LOG_FILE}."
fi

echo "Backup verification passed; latest snapshot is ${age_hours}h old."
echo "=== Qacey backup verification finished: $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
