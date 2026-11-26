#!/usr/bin/env bash
# =============================================================================
# reset.sh — Full wipe of Qacey Platform
# =============================================================================
# Stops all services, removes Docker volumes, wipes .env files and the
# initialisation sentinel. Use before re-running setup.sh.
# WARNING: All data (DB, Redis, certs, uploads) will be permanently deleted.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
set_platform_compose_env_args "${PLATFORM_DIR}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

echo ""
echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║          FULL RESET — ALL DATA WILL BE DELETED              ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
warn "This will:"
warn "  • Stop all running containers"
warn "  • Delete all Docker volumes (database, Redis, uploads, certs)"
warn "  • Delete .env files"
warn "  • Remove .qacey-initialized sentinel"
echo ""
read -rp "Type RESET to confirm: " CONFIRM
[[ "${CONFIRM}" == "RESET" ]] || die "Aborted."

# ── Shared-project guard ──────────────────────────────────────────────────────
if docker ps -a --filter label=com.docker.compose.project=qacey-platform \
  --format '{{.Names}}' | grep -qx 'archon'; then
  die "Archon shares the qacey-platform project name. Rename its Compose project before running reset; refusing to delete shared-project volumes."
fi

# ── Stop services ─────────────────────────────────────────────────────────────
info "Stopping services..."
docker compose \
  -f "${PLATFORM_DIR}/docker-compose.platform.yml" \
  "${COMPOSE_ENV_ARGS[@]}" \
  --project-name qacey-platform \
  down --volumes 2>/dev/null || true
success "Services stopped and volumes removed."

# ── Remove Docker networks ────────────────────────────────────────────────────
info "Removing Docker networks..."
docker network rm qacey-proxy    2>/dev/null && success "Removed qacey-proxy."    || warn "qacey-proxy not found."
docker network rm qacey-internal 2>/dev/null && success "Removed qacey-internal." || warn "qacey-internal not found."

# ── Wipe host directories ─────────────────────────────────────────────────────
info "Wiping /opt/qacey/traefik/certs/acme.json ..."
sudo rm -f /opt/qacey/traefik/certs/acme.json || true
success "Certs wiped."

# ── Remove .env files ─────────────────────────────────────────────────────────
info "Removing .env files..."
rm -f "${PLATFORM_DIR}/.env"
rm -f "${PLATFORM_DIR}/secrets/.env"
success ".env files removed."

# ── Remove sentinel ───────────────────────────────────────────────────────────
rm -f "${PLATFORM_DIR}/.qacey-initialized"
success "Sentinel removed."

echo ""
success "Reset complete. Run scripts/setup.sh to start fresh."
echo ""
