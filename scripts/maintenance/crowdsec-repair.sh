#!/usr/bin/env bash
# =============================================================================
# scripts/crowdsec-repair.sh — Re-register CrowdSec bouncer keys
# =============================================================================
# U-12: Updated for maxlerebourg/crowdsec-bouncer-traefik-plugin.
# The plugin runs inside Traefik (no separate bouncer container).
# Run this when Traefik logs show bouncer auth errors or 403s appear.
#
# Common causes:
#   - CrowdSec container was recreated (config volume wiped → bouncer key lost)
#   - CROWDSEC_ORACLE_NET_IP changed after oracle-deploy.sh re-ran
#   - First deploy: bouncer key was generated but not yet registered
#
# Usage:
#   # Home server (run as the deploy user, not root):
#   bash scripts/crowdsec-repair.sh
#
#   # Oracle VPS (run as root):
#   sudo bash scripts/crowdsec-repair.sh --oracle
#
# Idempotent — safe to re-run at any time.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC}   $*" >&2; exit 1; }

ORACLE_MODE=false
for arg in "$@"; do
  [[ "$arg" == "--oracle" ]] && ORACLE_MODE=true
done

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         CrowdSec Bouncer Key Repair                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [[ "$ORACLE_MODE" == "true" ]]; then
  # ── Oracle VPS mode ────────────────────────────────────────────────────────
  [[ $EUID -eq 0 ]] || error "Oracle mode requires root: sudo bash scripts/crowdsec-repair.sh --oracle"

  ENV_FILE="$REPO_ROOT/.env.oracle"
  VERSIONS_FILE="$REPO_ROOT/versions.env"
  COMPOSE_FILE="$REPO_ROOT/docker-compose.oracle.yml"

  [[ -f "$ENV_FILE" ]] || error ".env.oracle not found."

  # Load current key from env
  set +u
  # shellcheck disable=SC1090
  source <(grep -E "^CROWDSEC_ORACLE_LAPI_KEY=|^QACEY_DOMAIN=" "$ENV_FILE" 2>/dev/null || true)
  if [[ -z "${QACEY_DOMAIN:-}" ]]; then
    error "QACEY_DOMAIN not set in .env.oracle"
  fi
  set -u

  if [[ -z "${CROWDSEC_ORACLE_LAPI_KEY:-}" ]]; then
    info "Generating new CrowdSec Oracle bouncer key..."
    CROWDSEC_ORACLE_LAPI_KEY="$(openssl rand -hex 32)"
    if grep -q "^CROWDSEC_ORACLE_LAPI_KEY=" "$ENV_FILE"; then
      sed -i "s|^CROWDSEC_ORACLE_LAPI_KEY=.*|CROWDSEC_ORACLE_LAPI_KEY=${CROWDSEC_ORACLE_LAPI_KEY}|" "$ENV_FILE"
    else
      echo "CROWDSEC_ORACLE_LAPI_KEY=${CROWDSEC_ORACLE_LAPI_KEY}" >> "$ENV_FILE"
    fi
    success "New key generated and saved to .env.oracle"
  else
    info "Using existing CROWDSEC_ORACLE_LAPI_KEY from .env.oracle"
  fi

  # Wait for CrowdSec LAPI
  info "Waiting for crowdsec-oracle LAPI (up to 30s)..."
  WAITED=0
  until docker exec crowdsec-oracle cscli bouncers list &>/dev/null; do
    sleep 2; WAITED=$((WAITED+2))
    [[ $WAITED -lt 30 ]] || error "crowdsec-oracle not ready. Check: docker logs crowdsec-oracle"
  done
  success "CrowdSec LAPI ready."

  # Remove stale registration if present, then re-add
  if docker exec crowdsec-oracle cscli bouncers list 2>/dev/null | grep -q "oracle-traefik-bouncer"; then
    info "Removing stale bouncer registration..."
    docker exec crowdsec-oracle cscli bouncers delete oracle-traefik-bouncer 2>/dev/null || true
  fi

  docker exec crowdsec-oracle cscli bouncers add oracle-traefik-bouncer \
    --key "${CROWDSEC_ORACLE_LAPI_KEY}" \
    && success "Bouncer 'oracle-traefik-bouncer' registered." \
    || error "Failed to register bouncer. Check: docker logs crowdsec-oracle"

  # Update CROWDSEC_ORACLE_NET_IP — crowdsec-oracle has static IP 172.19.0.10
  CROWDSEC_NET_IP="172.19.0.10"
  if grep -q "^CROWDSEC_ORACLE_NET_IP=" "$ENV_FILE"; then
    sed -i "s|^CROWDSEC_ORACLE_NET_IP=.*|CROWDSEC_ORACLE_NET_IP=${CROWDSEC_NET_IP}|" "$ENV_FILE"
  else
    echo "CROWDSEC_ORACLE_NET_IP=${CROWDSEC_NET_IP}" >> "$ENV_FILE"
  fi
  success "CROWDSEC_ORACLE_NET_IP confirmed: ${CROWDSEC_NET_IP}"

  # Re-render passthrough.yml with the current key so Traefik picks it up
  # (Traefik hot-reloads dynamic config — no restart needed after this)
  TEMPLATE="$REPO_ROOT/infrastructure/traefik/oracle/dynamic/passthrough.yml"
  RENDERED="/opt/qacey/traefik/oracle/dynamic/passthrough.yml"
  if [[ -f "$TEMPLATE" ]] && [[ -d "/opt/qacey/traefik/oracle/dynamic" ]]; then
    sed \
      -e "s|\${CROWDSEC_ORACLE_LAPI_KEY}|${CROWDSEC_ORACLE_LAPI_KEY}|g" \
      -e "s|\${CROWDSEC_ORACLE_NET_IP}|${CROWDSEC_NET_IP}|g" \
      -e "s|\${QACEY_DOMAIN}|${QACEY_DOMAIN}|g" \
      "$TEMPLATE" > "$RENDERED"
    chmod 600 "$RENDERED"
    success "passthrough.yml re-rendered with current key (Traefik hot-reloads in ~2s)"
  else
    warn "Could not re-render passthrough.yml — run oracle-deploy.sh to fix"
  fi

  # Restart oracle-traefik so the plugin picks up the new key
  info "Restarting oracle-traefik (plugin reads key from dynamic config)..."
  docker restart oracle-traefik
  success "oracle-traefik restarted."

  # Wait for Traefik to fully bind ports (the 'closed network connection' errors
  # during restart are normal — they clear once the process rebinds)
  info "Waiting 15s for Traefik to fully start..."
  sleep 15

  # Check for actual bouncer auth errors (not normal restart noise)
  info "Checking oracle-traefik logs for bouncer errors..."
  BOUNCER_ERRORS="$(docker logs oracle-traefik --since 10s 2>&1 | grep -iE "crowdsec.*error|bouncer.*error|validateParams|statusCode:403" || true)"
  if [[ -z "$BOUNCER_ERRORS" ]]; then
    success "No bouncer errors in oracle-traefik logs."
  else
    warn "oracle-traefik bouncer errors detected:"
    echo "$BOUNCER_ERRORS"
  fi

  # Verify external access
  info "Verifying external access..."
  HTTP_CODE="$(curl -so /dev/null -w '%{http_code}' --max-time 15 \
    https://files.${QACEY_DOMAIN} 2>/dev/null || echo "000")"
  if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "302" ]]; then
    success "External access OK (HTTP $HTTP_CODE) — bouncer is working correctly."
  else
    warn "External access returned HTTP $HTTP_CODE — check oracle-traefik logs"
    warn "Note: HTTP 000 immediately after restart is normal (Traefik still binding ports)"
    warn "Wait 10s and run: curl -sI https://files.${QACEY_DOMAIN} | head -1"
  fi

else
  # ── Home server mode ───────────────────────────────────────────────────────
  ENV_FILE="$REPO_ROOT/.env"
  SECRETS_ENV_FILE="$REPO_ROOT/secrets/.env"
  VERSIONS_FILE="$REPO_ROOT/versions.env"
  COMPOSE_FILE="$REPO_ROOT/docker-compose.platform.yml"

  [[ -f "$ENV_FILE" ]] || error ".env not found."

  # Load public config plus private secret overlay.
  # shellcheck disable=SC1091
  source "$REPO_ROOT/scripts/lib/platform-env.sh"
  load_platform_env "$REPO_ROOT" || error "Could not load platform environment"

  if [[ -z "${CROWDSEC_LAPI_KEY:-}" ]]; then
    info "Generating new CrowdSec home bouncer key..."
    CROWDSEC_LAPI_KEY="$(openssl rand -hex 32)"
    mkdir -p "$(dirname "$SECRETS_ENV_FILE")"
    touch "$SECRETS_ENV_FILE"
    if grep -q "^CROWDSEC_LAPI_KEY=" "$SECRETS_ENV_FILE"; then
      sed -i "s|^CROWDSEC_LAPI_KEY=.*|CROWDSEC_LAPI_KEY=${CROWDSEC_LAPI_KEY}|" "$SECRETS_ENV_FILE"
    else
      echo "CROWDSEC_LAPI_KEY=${CROWDSEC_LAPI_KEY}" >> "$SECRETS_ENV_FILE"
    fi
    chmod 600 "$SECRETS_ENV_FILE"
    success "New key generated and saved to secrets/.env"
  else
    info "Using existing CROWDSEC_LAPI_KEY from .env"
  fi

  # Wait for CrowdSec LAPI
  info "Waiting for crowdsec LAPI (up to 30s)..."
  WAITED=0
  until docker exec crowdsec cscli bouncers list &>/dev/null; do
    sleep 2; WAITED=$((WAITED+2))
    [[ $WAITED -lt 30 ]] || error "crowdsec not ready. Check: docker logs crowdsec"
  done
  success "CrowdSec LAPI ready."

  # Remove stale registration if present, then re-add
  if docker exec crowdsec cscli bouncers list 2>/dev/null | grep -q "traefik-bouncer"; then
    info "Removing stale bouncer registration..."
    docker exec crowdsec cscli bouncers delete traefik-bouncer 2>/dev/null || true
  fi

  docker exec crowdsec cscli bouncers add traefik-bouncer \
    --key "${CROWDSEC_LAPI_KEY}" \
    && success "Bouncer 'traefik-bouncer' registered." \
    || error "Failed to register bouncer. Check: docker logs crowdsec"

  # Restart Traefik so the plugin picks up the new key
  info "Restarting traefik (plugin reads key from dynamic config)..."
  docker restart traefik
  success "traefik restarted."

  # Verify — plugin is inside Traefik, check logs for bouncer errors
  sleep 5
  info "Checking traefik logs for bouncer errors..."
  BOUNCER_ERRORS="$(docker logs traefik --tail 20 2>&1 | grep -i "bouncer\|crowdsec\|error" || true)"
  if [[ -z "$BOUNCER_ERRORS" ]]; then
    success "No bouncer errors in traefik logs."
  else
    warn "traefik log output (check for errors):"
    echo "$BOUNCER_ERRORS"
  fi

  info "Verifying services respond..."
  HTTP_CODE="$(curl -so /dev/null -w '%{http_code}' --max-time 10 \
    https://files.${QACEY_DOMAIN} 2>/dev/null || echo "000")"
  if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "302" ]]; then
    success "Services OK (HTTP $HTTP_CODE)"
  else
    warn "HTTP $HTTP_CODE — check: docker logs traefik --tail 30"
    warn "Also verify: docker exec crowdsec cscli bouncers list"
  fi
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         CrowdSec Repair Complete                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Check bouncer registration:"
echo "  Home:   docker exec crowdsec cscli bouncers list"
echo "  Oracle: docker exec crowdsec-oracle cscli bouncers list"
echo ""
echo "  Check Traefik plugin logs:"
echo "  Home:   docker logs traefik --tail 30"
echo "  Oracle: docker logs oracle-traefik --tail 30"
echo ""
