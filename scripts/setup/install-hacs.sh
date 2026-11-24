#!/usr/bin/env bash
# =============================================================================
# scripts/setup/install-hacs.sh — Install HACS in Home Assistant
# =============================================================================
# HACS (Home Assistant Community Store) is required for installing custom
# integrations like MyEnergi.
#
# Usage:
#   bash scripts/setup/install-hacs.sh
#
# Prerequisites:
#   - Home Assistant container must be running
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

# ── Check if Home Assistant is running ───────────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q '^homeassistant$'; then
  error "Home Assistant container is not running. Start it first with:"
  echo "  docker compose -f docker-compose.platform.yml up -d homeassistant"
  exit 1
fi

# ── Check if HACS is already installed ───────────────────────────────────────
if docker exec homeassistant test -d /config/custom_components/hacs 2>/dev/null; then
  warn "HACS is already installed."
  info "To reinstall, remove it first:"
  echo "  docker exec homeassistant rm -rf /config/custom_components/hacs"
  exit 0
fi

# ── Install HACS ──────────────────────────────────────────────────────────────
info "Installing HACS (Home Assistant Community Store)..."

docker exec homeassistant bash -c "wget -O - https://get.hacs.xyz | bash -" || {
  error "HACS installation failed."
  exit 1
}

success "HACS installed successfully."

# ── Restart Home Assistant ───────────────────────────────────────────────────
info "Restarting Home Assistant to load HACS..."
docker restart homeassistant

info "Waiting for Home Assistant to start..."
sleep 30

# ── Verify installation ───────────────────────────────────────────────────────
if docker exec homeassistant test -d /config/custom_components/hacs 2>/dev/null; then
  success "HACS is ready!"
  echo ""
  info "Next steps:"
  echo "  1. Open Home Assistant: https://homeassistant.example.com"
  echo "  2. Go to Settings → Devices & Services"
  echo "  3. Click '+ Add Integration' and search for 'HACS'"
  echo "  4. Follow the setup wizard to authenticate with GitHub"
  echo ""
  info "After HACS is configured, you can install custom integrations like MyEnergi."
else
  error "HACS installation verification failed."
  exit 1
fi
