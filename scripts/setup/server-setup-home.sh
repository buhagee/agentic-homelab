#!/usr/bin/env bash
# =============================================================================
# scripts/server-setup-home.sh — Home server OS hardening
# =============================================================================
# Idempotent — safe to re-run at any time. Each step checks current state
# before making changes.
#
# Run on the home server as root:
#   sudo bash scripts/server-setup-home.sh
#
# What this script does:
#   1. Install required packages (wireguard-tools, etc.)
#   2. Unattended-upgrades: enable auto-reboot at 03:00
#   3. fail2ban: tune to 3 retries, 1h incremental ban
#   4. sysctl network hardening
#   5. UFW: add WireGuard rule (UDP 51820, LAN-only), restrict go2rtc
#   6. CrowdSec: install sshd collection + add sshd log acquisition
#   7. Docker daemon log limits (10m/3 files — prevents log bloat)
#   8. Node.js heap cap (256 MB via NODE_OPTIONS — prevents OOM)
#   9. Qacey drive mount points + directory structure (/mnt/ssd, /mnt/hdd1, /mnt/hdd2)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
load_platform_env "${PLATFORM_DIR}" || exit 1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC}   $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || error "Run as root: sudo bash scripts/server-setup-home.sh"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         Qacey Home Server — OS Hardening                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 0. SSH hardening ──────────────────────────────────────────────────────────
info "0/8 Hardening SSH..."

SSHD_CONF="/etc/ssh/sshd_config"
[[ -f "${SSHD_CONF}.bak" ]] || cp "$SSHD_CONF" "${SSHD_CONF}.bak"

set_sshd() {
  local key="$1" val="$2"
  if grep -qE "^#?${key}" "$SSHD_CONF"; then
    sed -i "s|^#\?${key}.*|${key} ${val}|" "$SSHD_CONF"
  else
    echo "${key} ${val}" >> "$SSHD_CONF"
  fi
}

set_sshd "PasswordAuthentication" "no"
set_sshd "PubkeyAuthentication"   "yes"
set_sshd "PermitRootLogin"        "no"
set_sshd "MaxAuthTries"           "3"
set_sshd "LoginGraceTime"         "30"

if systemctl is-active --quiet ssh 2>/dev/null; then
  systemctl restart ssh
elif systemctl is-active --quiet sshd 2>/dev/null; then
  systemctl restart sshd
fi
success "SSH hardened (key-only, MaxAuthTries=3, LoginGraceTime=30)."

# ── 1. Install packages ───────────────────────────────────────────────────────
info "1/8 Installing required packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard-tools
success "Packages installed."

# ── 2. Unattended-upgrades: auto-reboot ──────────────────────────────────────
info "2/6 Configuring unattended-upgrades auto-reboot..."

UNATTENDED_CONF="/etc/apt/apt.conf.d/50unattended-upgrades"
if [[ -f "$UNATTENDED_CONF" ]]; then
  if grep -q '//Unattended-Upgrade::Automatic-Reboot ' "$UNATTENDED_CONF"; then
    sed -i 's|//Unattended-Upgrade::Automatic-Reboot .*|Unattended-Upgrade::Automatic-Reboot "true";|' "$UNATTENDED_CONF"
  elif ! grep -q '^Unattended-Upgrade::Automatic-Reboot ' "$UNATTENDED_CONF"; then
    echo 'Unattended-Upgrade::Automatic-Reboot "true";' >> "$UNATTENDED_CONF"
  fi
  if grep -q '//Unattended-Upgrade::Automatic-Reboot-Time' "$UNATTENDED_CONF"; then
    sed -i 's|//Unattended-Upgrade::Automatic-Reboot-Time.*|Unattended-Upgrade::Automatic-Reboot-Time "03:00";|' "$UNATTENDED_CONF"
  elif ! grep -q '^Unattended-Upgrade::Automatic-Reboot-Time' "$UNATTENDED_CONF"; then
    echo 'Unattended-Upgrade::Automatic-Reboot-Time "03:00";' >> "$UNATTENDED_CONF"
  fi
  systemctl restart unattended-upgrades
  success "Auto-reboot at 03:00 enabled."
else
  warn "50unattended-upgrades not found — skipping auto-reboot config."
fi

# ── 3. fail2ban tuning ────────────────────────────────────────────────────────
info "3/6 Tuning fail2ban..."

# Only write jail.local if it doesn't already have our tuning
if ! grep -q "bantime.increment" /etc/fail2ban/jail.local 2>/dev/null; then
  cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
# Incremental bans: 1h → 2h → 4h → ... (up to 1 week)
bantime             = 3600
bantime.increment   = true
bantime.maxtime     = 604800
bantime.factor      = 1
findtime            = 600
maxretry            = 3
backend             = systemd
banaction           = nftables
banaction_allports  = nftables[type=allports]

[sshd]
enabled  = true
port     = 22
backend  = systemd
journalmatch = _SYSTEMD_UNIT=ssh.service + _COMM=sshd
EOF
  systemctl restart fail2ban
  success "fail2ban tuned (3 retries → 1h ban, incremental)."
else
  success "fail2ban already tuned — skipping."
fi

# ── 4. sysctl hardening ───────────────────────────────────────────────────────
info "4/6 Applying sysctl network hardening..."

cat > /etc/sysctl.d/99-qacey-hardening.conf <<'EOF'
# Qacey Platform — network hardening
# Applied by server-setup-home.sh

# Reverse path filtering — strict mode
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# SYN flood protection
net.ipv4.tcp_syncookies = 1

# Ignore ICMP redirects
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Do not send ICMP redirects
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0

# Ignore source-routed packets
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0

# Log martian packets
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1

# Ignore ICMP broadcast pings
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Ignore bogus ICMP error responses
net.ipv4.icmp_ignore_bogus_error_responses = 1

# IP forwarding — required for WireGuard
net.ipv4.ip_forward = 1

# Memory management — reduce swap aggressiveness
# Default is 60 (aggressive swapping for disk cache)
# 10 = only swap when necessary, prefer keeping programs in RAM
vm.swappiness = 10
EOF

sysctl --system -q
success "sysctl hardening applied (including swappiness=10)."

# ── 5. UFW rules ──────────────────────────────────────────────────────────────
info "5/8 Updating UFW rules..."

# WireGuard: only accept from Oracle VPS IP (not open to world)
ORACLE_IP="${ORACLE_IP:-}"
[[ -n "$ORACLE_IP" ]] || error "ORACLE_IP not set in .env"
if ! ufw status | grep -q "51820/udp.*${ORACLE_IP}"; then
  ufw allow from "${ORACLE_IP}" to any port 51820 proto udp comment "WireGuard tunnel (Oracle VPS)"
  success "UFW: WireGuard UDP 51820 allowed from Oracle VPS."
else
  success "UFW: WireGuard rule already present."
fi

# go2rtc (Home Assistant WebRTC) — restrict to LAN only
if ! ufw status | grep -q "18555"; then
  ufw allow from 192.168.0.0/16 to any port 18555 comment "go2rtc WebRTC (LAN only)"
  success "UFW: go2rtc port 18555 restricted to LAN."
else
  success "UFW: go2rtc rule already present."
fi

# AdGuard Home — host network mode requires explicit UFW rules
# Port 3000: web UI (LAN only)
if ! ufw status | grep -q "3000/tcp"; then
  ufw allow from 192.168.0.0/16 to any port 3000 proto tcp comment "AdGuard Home web UI (LAN only)"
  success "UFW: AdGuard web UI port 3000 allowed from LAN."
else
  success "UFW: AdGuard web UI rule already present."
fi
# Port 3000 from Docker networks: Traefik reaches the host-mode AdGuard container
# through host.docker.internal, whose source address is a Docker subnet.
if ! ufw status | grep -q "3000.*172.16.0.0/12"; then
  ufw allow from 172.16.0.0/12 to any port 3000 proto tcp comment "Docker networks -> AdGuard web UI"
  success "UFW: AdGuard web UI reachable from Docker networks."
else
  success "UFW: Docker AdGuard web UI rule already present."
fi
# Port 53: DNS (LAN + any for external resolution)
if ! ufw status | grep -q "53/udp"; then
  ufw allow from 192.168.0.0/16 to any port 53 comment "AdGuard DNS (LAN)"
  ufw allow 53/udp comment "AdGuard DNS (UDP)"
  success "UFW: AdGuard DNS port 53 allowed."
else
  success "UFW: AdGuard DNS rule already present."
fi
# Ports 67/68: DHCP server/client
if ! ufw status | grep -q "67/udp"; then
  ufw allow 67/udp comment "AdGuard DHCP server"
  ufw allow 68/udp comment "AdGuard DHCP client"
  success "UFW: AdGuard DHCP ports 67/68 allowed."
else
  success "UFW: AdGuard DHCP rules already present."
fi

ufw reload
success "UFW rules updated."

# ── 6. CrowdSec: sshd collection ─────────────────────────────────────────────
info "6/8 Configuring CrowdSec sshd collection..."

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^crowdsec$"; then
  # Install sshd collection if not already installed
  if ! docker exec crowdsec cscli collections list 2>/dev/null | grep -q "crowdsecurity/sshd"; then
    docker exec crowdsec cscli collections install crowdsecurity/sshd
    success "CrowdSec: crowdsecurity/sshd collection installed."
  else
    success "CrowdSec: crowdsecurity/sshd already installed."
  fi

  # Check if sshd acquisition is already in acquis.yaml
  ACQUIS_FILE="${PLATFORM_DIR}/infrastructure/crowdsec/acquis.yaml"
  if [[ -f "$ACQUIS_FILE" ]] && ! grep -q "sshd\|auth.log\|journald" "$ACQUIS_FILE"; then
    cat >> "$ACQUIS_FILE" <<'EOF'

---
# SSH brute-force detection via systemd journal
source: journald
journalctl_filter:
  - "_SYSTEMD_UNIT=ssh.service"
labels:
  type: syslog
EOF
    success "CrowdSec: sshd acquisition added to acquis.yaml."
    # Restart crowdsec to pick up new acquisition
    docker restart crowdsec
    success "CrowdSec restarted."
  else
    success "CrowdSec: sshd acquisition already configured."
  fi
else
  warn "CrowdSec container not running — skipping sshd collection setup."
  warn "Run this script again after 'bash scripts/start.sh'."
fi

# ── 7. Docker daemon log limits ───────────────────────────────────────────────
# Docker keeps container logs indefinitely unless capped, inflating dockerd
# and systemd-journald memory over time. Sets a global default so every
# container is covered. Per-container overrides in compose files take precedence.
info "7/8 Configuring Docker daemon log limits..."

DOCKER_DAEMON_JSON="/etc/docker/daemon.json"

if [[ -f "$DOCKER_DAEMON_JSON" ]]; then
  if python3 -c "import json,sys; d=json.load(open('$DOCKER_DAEMON_JSON')); sys.exit(0 if d.get('log-driver')=='json-file' else 1)" 2>/dev/null; then
    success "  Docker log limits already configured — skipping."
  else
    python3 - <<'PYEOF'
import json
path = "/etc/docker/daemon.json"
try:
    with open(path) as f:
        d = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    d = {}
d["log-driver"] = "json-file"
d.setdefault("log-opts", {})
d["log-opts"]["max-size"] = "10m"
d["log-opts"]["max-file"] = "3"
with open(path, "w") as f:
    json.dump(d, f, indent=2)
    f.write("\n")
PYEOF
    systemctl reload docker 2>/dev/null || systemctl restart docker
    success "  Docker log limits set (10m / 3 files per container)."
  fi
else
  cat > "$DOCKER_DAEMON_JSON" <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
  if systemctl is-active --quiet docker 2>/dev/null; then
    systemctl reload docker 2>/dev/null || systemctl restart docker
  fi
  success "  Docker daemon.json created with log limits."
fi

# ── 8. Node.js heap memory cap ────────────────────────────────────────────────
# Node.js defaults to ~1.5 GB heap before GC kicks in. Cap at 256 MB for
# any Node.js processes started in a login shell on the host.
# Container-level Node processes need --max-old-space-size in their CMD.
info "8/8 Capping Node.js heap memory..."

NODE_OPTIONS_LINE='NODE_OPTIONS="--max-old-space-size=256"'
if ! grep -q "max-old-space-size" /etc/environment 2>/dev/null; then
  echo "$NODE_OPTIONS_LINE" >> /etc/environment
  success "  NODE_OPTIONS set in /etc/environment (256 MB heap cap)."
else
  success "  Node.js heap cap already set — skipping."
fi

# ── 9. Qacey drive mount points + directory structure ─────────────────────────
info "9/9 Creating qacey drive mount points and directory structure..."

# Mount points
for mp in /mnt/ssd /mnt/hdd1 /mnt/hdd2; do
  if [[ ! -d "$mp" ]]; then
    mkdir -p "$mp"
    success "  Created mount point $mp"
  fi
done

# SSD directory structure (fast tier: databases, config, runtime)
SSD_DIRS=(
  /mnt/ssd/qacey/postgres/immich
  /mnt/ssd/qacey/postgres/mnemo
  /mnt/ssd/qacey/vaultwarden
  /mnt/ssd/qacey/hermes/justin
  /mnt/ssd/qacey/hermes/annique
  /mnt/ssd/qacey/hermes/skills
  /mnt/ssd/qacey/traefik
  /mnt/ssd/qacey/adguard
  /mnt/ssd/qacey/crowdsec
  /mnt/ssd/qacey/wireguard
  /mnt/ssd/qacey/homeassistant
  /mnt/ssd/qacey/scrutiny
  /mnt/ssd/qacey/immich-model-cache
)
for d in "${SSD_DIRS[@]}"; do mkdir -p "$d"; done

# HDD1 directory structure (bulk media: Immich uploads)
HDD1_DIRS=(
  /mnt/hdd1/qacey/immich
  /mnt/hdd1/qacey/db-backups
)
for d in "${HDD1_DIRS[@]}"; do mkdir -p "$d"; done

# HDD2 directory structure (mirror: populated by backup script only)
HDD2_DIRS=(
  /mnt/hdd2/qacey/ssd-mirror
  /mnt/hdd2/qacey/hdd1-mirror
)
for d in "${HDD2_DIRS[@]}"; do mkdir -p "$d"; done

# Hand ownership to the platform user
chown -R buhagiar:buhagiar /mnt/ssd/qacey /mnt/hdd1/qacey /mnt/hdd2/qacey
success "  Directory structure created and owned by buhagiar."

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         Home Server OS Hardening Complete                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Next steps:"
echo "  1. bash scripts/start.sh  — deploy WireGuard client container"
echo "  2. Verify tunnel: docker exec wireguard-home wg show"
echo "  3. Complete the DNS cutover in the AdGuard admin UI"
echo ""
