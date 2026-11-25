#!/usr/bin/env bash
# =============================================================================
# build.sh — Build local images and pull latest pre-built images, then start
# =============================================================================
# Local images built here:
#   qacey/hermes-agent:local  — custom Hermes agent
#   qacey/mcp-*:local         — MCP server images
#
# Usage:
#   bash scripts/build.sh           # build all local images, pull others, start
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ -f "${PLATFORM_DIR}/.env" ]] || { echo "ERROR: .env not found. Run first-time-setup.sh first." >&2; exit 1; }
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
set_platform_compose_env_args "${PLATFORM_DIR}"

COMPOSE_CMD=(docker compose -f "${PLATFORM_DIR}/docker-compose.platform.yml" "${COMPOSE_ENV_ARGS[@]}" --project-name qacey-platform)

# ── Build the Hermes agent image ─────────────────────────────────────────────
info "Building qacey/hermes-agent:local (agent + dashboard entrypoint)..."
HERMES_VERSION=$(grep -E '^HERMES_VERSION=' "${PLATFORM_DIR}/versions.env" | head -1 | cut -d= -f2- || true)
HERMES_VERSION=${HERMES_VERSION:-latest}
docker build \
  --build-arg "HERMES_VERSION=${HERMES_VERSION}" \
  -f "${PLATFORM_DIR}/services/agent/Dockerfile" \
  -t qacey/hermes-agent:local \
  "${PLATFORM_DIR}/services/agent"
success "qacey/hermes-agent:local built (hermes-agent ${HERMES_VERSION})."

# ── Pull latest images ────────────────────────────────────────────────────────
info "Pulling latest images..."
"${COMPOSE_CMD[@]}" pull --ignore-pull-failures 2>/dev/null || true
success "Image pull complete."

# ── Start all services ────────────────────────────────────────────────────────
info "Starting all services..."
"${COMPOSE_CMD[@]}" up -d
success "All services started."

echo ""
echo "  Run scripts/testing/smoke-test.sh to verify."
echo ""
