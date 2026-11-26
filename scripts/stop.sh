#!/usr/bin/env bash
# =============================================================================
# stop.sh — Stop all Qacey services (preserves data)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
set_platform_compose_env_args "${PLATFORM_DIR}"

echo "[INFO] Stopping declared Qacey services..."
mapfile -t services < <(
  docker compose \
    -f "${PLATFORM_DIR}/docker-compose.platform.yml" \
    "${COMPOSE_ENV_ARGS[@]}" \
    --project-name qacey-platform \
    config --services
)
docker compose \
  -f "${PLATFORM_DIR}/docker-compose.platform.yml" \
  "${COMPOSE_ENV_ARGS[@]}" \
  --project-name qacey-platform \
  stop "${services[@]}"

echo "[OK] Declared services stopped. Data preserved; unmanaged project containers left running."
