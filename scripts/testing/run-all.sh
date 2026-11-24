#!/usr/bin/env bash
# Aggregate test runner. Run from anywhere; --list prints the commands only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

COMMANDS=(
  "python3 -m unittest discover -s scripts/setup/tests"
  "python3 -m unittest discover -s scripts/testing/tests"
  "python3 -m unittest discover -s scripts/deploy/tests"
  "python3 -m unittest discover -s services/opencode-docker-control/tests"
  "python3 -m unittest discover -s services/agent/google_workspace_mcp/tests"
  "bash scripts/testing/check-secrets.sh"
  "bash -n scripts/deploy/homeserver-deploy"
  "find scripts -name '*.sh' -print0 | xargs -0 -n1 bash -n"
)

if [[ "${1:-}" == "--list" ]]; then
  printf '%s\n' "${COMMANDS[@]}"
  exit 0
fi

cd "${REPO_ROOT}"

for command in "${COMMANDS[@]}"; do
  echo "+ ${command}"
  bash -c "${command}"
done
