#!/usr/bin/env bash
# =============================================================================
# start.sh — Start all Qacey services
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

[[ -f "${PLATFORM_DIR}/.env" ]] || { echo "ERROR: .env not found. Run first-time-setup.sh first." >&2; exit 1; }
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
load_platform_env "${PLATFORM_DIR}"
set_platform_compose_env_args "${PLATFORM_DIR}"

# shellcheck source=scripts/lib/render-config.sh
source "${PLATFORM_DIR}/scripts/lib/render-config.sh"
render_traefik_dynamic "${PLATFORM_DIR}"

echo "[INFO] Starting Qacey services..."
docker compose \
  -f "${PLATFORM_DIR}/docker-compose.platform.yml" \
  "${COMPOSE_ENV_ARGS[@]}" \
  --project-name qacey-platform \
  up -d

echo "[OK] Services started."
