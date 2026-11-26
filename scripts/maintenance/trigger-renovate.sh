#!/usr/bin/env bash
# Trigger the GitHub-hosted Renovate workflow if it has not run recently.
# Runs on the homeserver; Renovate itself still runs on GitHub.
set -euo pipefail

REPO="${RENOVATE_REPO:-buhagee/agentic-homelab}"
WORKFLOW="${RENOVATE_WORKFLOW:-renovate.yml}"
RECENT_SECONDS="${RENOVATE_RECENT_SECONDS:-7200}"

command -v gh >/dev/null 2>&1 || { echo "ERROR: gh is not installed" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh is not authenticated for $(id -un)" >&2; exit 1; }

runs="$(gh run list --repo "$REPO" --workflow "$WORKFLOW" --limit 10 --json createdAt,status)"

if python3 - "$RECENT_SECONDS" "$runs" <<'PY'
import datetime
import json
import sys

threshold = int(sys.argv[1])
now = datetime.datetime.now(datetime.timezone.utc)
for run in json.loads(sys.argv[2]):
    created = datetime.datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
    if (now - created).total_seconds() < threshold:
        sys.exit(0)
sys.exit(1)
PY
then
  echo "A Renovate run started in the last ${RECENT_SECONDS}s; skipping"
  exit 0
fi

gh workflow run "$WORKFLOW" --repo "$REPO" --ref main
echo "Dispatched $WORKFLOW for $REPO"
