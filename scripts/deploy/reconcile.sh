#!/usr/bin/env bash
# Reconcile the host with origin/main. Runs every 10 minutes from systemd.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="${HOME}/.local/state/qacey-deploy"

cd "$PLATFORM_DIR"

git fetch --quiet origin main
TIP="$(git rev-parse origin/main)"

last_good="$(cat "${STATE_DIR}/last-good" 2>/dev/null || true)"
failed="$(cat "${STATE_DIR}/failed-sha" 2>/dev/null || true)"

if [[ "$TIP" == "$last_good" ]]; then
  # Retry native work deferred by an active coding session even without a new
  # merge. Unbootstrapped hosts keep the original no-op behaviour.
  if [[ -e /usr/local/sbin/qacey-dev-deploy || -L /usr/local/sbin/qacey-dev-deploy ]]; then
    exec bash scripts/deploy/auto-deploy.sh "$TIP"
  fi
  exit 0
fi
if [[ "$TIP" == "$failed" ]]; then
  # Retry an undelivered incident without retrying a failed platform revision.
  source scripts/lib/alert.sh
  observe_incident platform-deploy failed "Platform revision $TIP awaits a fix-forward."
  exit 0
fi

exec bash scripts/deploy/auto-deploy.sh "$TIP"
