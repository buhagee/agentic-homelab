#!/usr/bin/env bash
# Stop and remove temporary sandbox service/container.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

compose=(
  docker compose
  --project-name qacey-platform
  -f "${PLATFORM_DIR}/docker-compose.platform.yml"
  --env-file "${PLATFORM_DIR}/versions.env"
  --env-file "${PLATFORM_DIR}/.env"
)
if [[ -f "${PLATFORM_DIR}/secrets/.env" ]]; then
  compose+=(--env-file "${PLATFORM_DIR}/secrets/.env")
fi

"${compose[@]}" --profile sandbox stop hermes-sandbox-oauth2-proxy hermes-sandbox
"${compose[@]}" --profile sandbox rm --force hermes-sandbox-oauth2-proxy hermes-sandbox
