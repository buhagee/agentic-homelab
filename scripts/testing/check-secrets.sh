#!/usr/bin/env bash
# Scan a tree for credentials. Uses gitleaks when available, then always runs
# the dependency-free pattern scanner.
#
# Usage: check-secrets.sh [root]
# REQUIRE_GITLEAKS=1 makes a missing gitleaks a hard failure (publication).
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ROOT="$(cd "$ROOT" && pwd)"

if command -v gitleaks >/dev/null 2>&1; then
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    gitleaks git "$ROOT" --redact --no-banner
  else
    gitleaks dir "$ROOT" --redact --no-banner
  fi
elif [[ "${REQUIRE_GITLEAKS:-0}" == "1" ]]; then
  echo "ERROR: gitleaks is required for this scan but is not installed" >&2
  exit 1
else
  echo "[INFO] gitleaks not installed; using local pattern scanner only"
fi

python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check_secret_patterns.py" "$ROOT"
