#!/usr/bin/env bash
# =============================================================================
# scripts/setup-wireguard-home.sh — Write WireGuard client config on home server
# =============================================================================
# Run AFTER oracle-deploy.sh has generated keys and you've copied the peer
# values into the home server .env file.
#
# Usage:
#   sudo bash scripts/setup-wireguard-home.sh
#
# Pre-requisites:
#   .env must contain:
#     WIREGUARD_HOME_PRIVATE_KEY=<from oracle-deploy.sh output>
#     WIREGUARD_HOME_PUBLIC_KEY=<from oracle-deploy.sh output>
#     WIREGUARD_ORACLE_PUBLIC_KEY=<from oracle-deploy.sh output>
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This script lives in scripts/setup/, so the platform root is two levels up.
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC}   $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || error "Run as root: sudo bash scripts/setup-wireguard-home.sh"

# ── Load env vars ─────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
load_platform_env "${PLATFORM_DIR}" || error "Could not load platform environment"

HOME_PRIVATE_KEY="${WIREGUARD_HOME_PRIVATE_KEY:-}"
ORACLE_PUBLIC_KEY="${WIREGUARD_ORACLE_PUBLIC_KEY:-}"
ORACLE_IP="${ORACLE_IP:-}"

[[ -n "$HOME_PRIVATE_KEY" ]] || error "WIREGUARD_HOME_PRIVATE_KEY not set in .env."
[[ -n "$ORACLE_PUBLIC_KEY" ]] || error "WIREGUARD_ORACLE_PUBLIC_KEY not set in .env."
[[ -n "$ORACLE_IP" ]] || error "ORACLE_IP not set in .env."

# Traefik has a fixed IP on qacey-proxy set in docker-compose.platform.yml.
# This is stable across restarts — no dynamic resolution needed
TRAEFIK_IP="${TRAEFIK_PROXY_IP:-172.18.255.250}"
[[ -n "$TRAEFIK_IP" ]] || TRAEFIK_IP="172.18.255.250"
info "Traefik fixed IP on qacey-proxy: ${TRAEFIK_IP}"

# ── Create WireGuard config directory ────────────────────────────────────────
# Must match the bind mount in docker-compose.platform.yml:
#   wireguard-home mounts /mnt/ssd/qacey/wireguard/home:/config
WG_DIR="/mnt/ssd/qacey/wireguard/home"
mkdir -p "$WG_DIR"
chmod 700 "$WG_DIR"

# ── Write wg0.conf ────────────────────────────────────────────────────────────
WG_CONF="$WG_DIR/wg_confs/wg0.conf"
mkdir -p "$WG_DIR/wg_confs"

if [[ -f "$WG_CONF" ]]; then
  info "wg0.conf already exists — backing up and overwriting..."
  cp "$WG_CONF" "${WG_CONF}.bak"
fi

cat > "$WG_CONF" <<EOF
[Interface]
# Home server WireGuard client — tunnel IP: 10.100.0.2/24
Address = 10.100.0.2/24
PrivateKey = ${HOME_PRIVATE_KEY}
DNS = 1.1.1.1

# DNAT: forward inbound tunnel traffic on :443/:80 to Traefik container
# MASQUERADE: ensure return traffic from Traefik routes back through the tunnel
PostUp   = iptables -t nat -A PREROUTING  -i wg0 -p tcp --dport 443 -j DNAT --to-destination ${TRAEFIK_IP}:443
PostUp   = iptables -t nat -A PREROUTING  -i wg0 -p tcp --dport 80  -j DNAT --to-destination ${TRAEFIK_IP}:80
PostUp   = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostUp   = iptables -t nat -A POSTROUTING -o eth1 -j MASQUERADE
PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT
PostUp   = iptables -A FORWARD -o wg0 -j ACCEPT
PostDown = iptables -t nat -D PREROUTING  -i wg0 -p tcp --dport 443 -j DNAT --to-destination ${TRAEFIK_IP}:443
PostDown = iptables -t nat -D PREROUTING  -i wg0 -p tcp --dport 80  -j DNAT --to-destination ${TRAEFIK_IP}:80
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -t nat -D POSTROUTING -o eth1 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -o wg0 -j ACCEPT

[Peer]
# Oracle VPS WireGuard server
PublicKey = ${ORACLE_PUBLIC_KEY}
Endpoint = ${ORACLE_IP}:51820
AllowedIPs = 10.100.0.0/24
PersistentKeepalive = 25
EOF

chmod 600 "$WG_CONF"
success "WireGuard client config written to $WG_CONF"

echo ""
info "Config written. Restart the wireguard-home container to apply it:"
info "  docker compose -f docker-compose.platform.yml --env-file versions.env --env-file .env restart wireguard-home"
info "Then verify: docker exec wireguard-home wg show"
echo ""
