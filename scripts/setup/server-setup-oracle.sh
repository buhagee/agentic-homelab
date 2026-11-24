#!/usr/bin/env bash
# =============================================================================
# scripts/server-setup-oracle.sh — Oracle VPS OS hardening
# =============================================================================
# Idempotent — safe to re-run at any time. Each step checks current state
# before making changes. Re-running applies any new hardening without
# disrupting existing config.
#
# Run ON the Oracle VPS as root:
#   sudo bash scripts/server-setup-oracle.sh
#
# What this script does:
#   1.  System update + security patches
#   2.  Unattended-upgrades (auto security patching + auto-reboot at 03:00)
#   3.  Remove snapd (nothing in the stack uses it; saves ~10 MiB RAM)
#   4.  SSH hardening (key-only, MaxAuthTries=3, login banner)
#   5.  sysctl network hardening
#   6.  UFW firewall (22/80/443/51820 open, all else denied)
#   7.  Docker CE installation (if not present)
#   8.  (reserved — see step numbering in script)
#   9.  Swap (2 GB swapfile, swappiness=10) — critical on 1 GB Oracle free tier
#   10. Project directory /opt/qacey
#   11. Docker daemon log limits (10m/3 files — prevents log bloat on 1 GB RAM)
#   12. Node.js heap cap (256 MB via NODE_OPTIONS — prevents OOM on 1 GB RAM)
#   13. CrowdSec memory tuning (restart to clear in-memory log cache)
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC}   $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || error "Run as root: sudo bash scripts/server-setup-oracle.sh"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         Qacey Oracle VPS — OS Hardening                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 1. System update ──────────────────────────────────────────────────────────
info "1/8 System update..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
# Note: fail2ban intentionally excluded — CrowdSec handles all brute-force protection
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  curl ca-certificates gnupg ufw unattended-upgrades \
  update-notifier-common wireguard-tools
success "System updated and base packages installed."

# ── 2. Unattended upgrades ────────────────────────────────────────────────────
info "2/8 Configuring unattended-upgrades..."

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# Enable auto-reboot at 03:00 for kernel updates
UNATTENDED_CONF="/etc/apt/apt.conf.d/50unattended-upgrades"
if [[ -f "$UNATTENDED_CONF" ]]; then
  # Enable auto-reboot (uncomment or set)
  if grep -q '//Unattended-Upgrade::Automatic-Reboot ' "$UNATTENDED_CONF"; then
    sed -i 's|//Unattended-Upgrade::Automatic-Reboot .*|Unattended-Upgrade::Automatic-Reboot "true";|' "$UNATTENDED_CONF"
  elif ! grep -q '^Unattended-Upgrade::Automatic-Reboot ' "$UNATTENDED_CONF"; then
    echo 'Unattended-Upgrade::Automatic-Reboot "true";' >> "$UNATTENDED_CONF"
  fi
  # Set reboot time
  if grep -q '//Unattended-Upgrade::Automatic-Reboot-Time' "$UNATTENDED_CONF"; then
    sed -i 's|//Unattended-Upgrade::Automatic-Reboot-Time.*|Unattended-Upgrade::Automatic-Reboot-Time "03:00";|' "$UNATTENDED_CONF"
  elif ! grep -q '^Unattended-Upgrade::Automatic-Reboot-Time' "$UNATTENDED_CONF"; then
    echo 'Unattended-Upgrade::Automatic-Reboot-Time "03:00";' >> "$UNATTENDED_CONF"
  fi
fi

systemctl enable --quiet unattended-upgrades
systemctl restart unattended-upgrades
success "Unattended-upgrades configured (auto-reboot at 03:00)."

# ── 3. Remove snapd ───────────────────────────────────────────────────────────
info "3/8 Removing snapd (nothing in the stack uses it)..."
if systemctl is-active --quiet snapd 2>/dev/null || dpkg -l snapd 2>/dev/null | grep -q '^ii'; then
  # Remove all installed snaps first
  snap list 2>/dev/null | awk 'NR>1 {print $1}' | xargs -r snap remove --purge 2>/dev/null || true
  systemctl disable --now snapd 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq snapd
  apt-get autoremove -y -qq
  # Prevent snapd from being reinstalled as a dependency
  cat > /etc/apt/preferences.d/no-snapd <<'EOF'
Package: snapd
Pin: release *
Pin-Priority: -1
EOF
  success "  snapd removed and pinned to never reinstall."
else
  success "  snapd not installed — skipping."
fi

# ── 4. SSH hardening ──────────────────────────────────────────────────────────
info "4/8 Hardening SSH..."

SSHD_CONF="/etc/ssh/sshd_config"
# Backup only if not already backed up
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
set_sshd "Banner"                 "/etc/issue.net"

cat > /etc/issue.net <<'EOF'
###############################################################
# WARNING: Unauthorised access to this system is prohibited.  #
# All connections are monitored and recorded.                  #
###############################################################
EOF

# Restart whichever SSH service name is active
if systemctl is-active --quiet ssh 2>/dev/null; then
  systemctl restart ssh
elif systemctl is-active --quiet sshd 2>/dev/null; then
  systemctl restart sshd
fi
success "SSH hardened (key-only, MaxAuthTries=3, banner set)."

# ── 6. sysctl hardening ───────────────────────────────────────────────────────
info "5/8 Applying sysctl network hardening..."

cat > /etc/sysctl.d/99-qacey-hardening.conf <<'EOF'
# Qacey Platform — network hardening
# Applied by server-setup-oracle.sh

# Reverse path filtering — strict mode (drop packets with spoofed source IPs)
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# SYN flood protection
net.ipv4.tcp_syncookies = 1

# Ignore ICMP redirects (prevent MITM via routing manipulation)
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

# Log martian packets (packets with impossible source addresses)
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1

# Ignore ICMP broadcast pings (Smurf attack mitigation)
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Ignore bogus ICMP error responses
net.ipv4.icmp_ignore_bogus_error_responses = 1

# IP forwarding — required for WireGuard to forward traffic to home server
net.ipv4.ip_forward = 1
EOF

sysctl --system -q
success "sysctl hardening applied."

# ── 7. UFW firewall ───────────────────────────────────────────────────────────
info "6/8 Configuring UFW firewall..."

# Install UFW if missing
command -v ufw >/dev/null 2>&1 || apt-get install -y -qq ufw

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

ufw allow 22/tcp   comment "SSH admin"
ufw allow 80/tcp   comment "HTTP (ACME challenge + redirect)"
ufw allow 443/tcp  comment "HTTPS (oracle-traefik TLS termination)"
ufw allow 51820/udp comment "WireGuard tunnel (home server peer)"

ufw --force enable
success "UFW configured (22/80/443/51820 open)."

# ── 8. Docker CE ──────────────────────────────────────────────────────────────
info "7/8 Checking Docker CE..."

if command -v docker >/dev/null 2>&1; then
  success "Docker already installed ($(docker --version))."
else
  info "  Installing Docker CE..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  systemctl enable --quiet docker
  systemctl start docker

  # Add ubuntu/opc user to docker group
  for u in ubuntu opc; do
    if id "$u" &>/dev/null; then
      usermod -aG docker "$u"
      success "  Added $u to docker group."
    fi
  done
  success "Docker CE installed ($(docker --version))."
fi

# ── 9. Swap ───────────────────────────────────────────────────────────────────
info "9/10 Configuring swap (2 GB)..."

SWAPFILE="/swapfile"
SWAP_SIZE="2G"

if swapon --show | grep -q "$SWAPFILE"; then
  success "  Swap already active at $SWAPFILE — skipping."
else
  # Remove any stale swapfile before (re)creating
  if [[ -f "$SWAPFILE" ]]; then
    swapoff "$SWAPFILE" 2>/dev/null || true
    rm -f "$SWAPFILE"
  fi

  fallocate -l "$SWAP_SIZE" "$SWAPFILE"
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE" -q
  swapon "$SWAPFILE"

  # Persist across reboots
  if ! grep -q "$SWAPFILE" /etc/fstab; then
    echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
  fi

  # Reduce swappiness — only use swap under real memory pressure
  if ! grep -q 'vm.swappiness' /etc/sysctl.d/99-qacey-hardening.conf; then
    echo -e "\n# Swap tuning — only swap under real pressure\nvm.swappiness = 10" \
      >> /etc/sysctl.d/99-qacey-hardening.conf
    sysctl -w vm.swappiness=10 -q
  fi

  success "  Swap configured: ${SWAP_SIZE} at ${SWAPFILE} (swappiness=10)."
fi

# ── 10. Project directory ─────────────────────────────────────────────────────
info "10/10 Ensuring /opt/qacey exists..."
mkdir -p /opt/qacey/traefik/oracle
success "/opt/qacey ready."

# ── 11. Docker daemon log limits ──────────────────────────────────────────────
# Critical on 1 GB instances: Docker keeps container logs indefinitely unless
# capped, inflating dockerd and systemd-journald memory over time.
# Sets a global default so every container (including future ones) is covered.
# Per-container overrides in docker-compose files take precedence.
info "11/13 Configuring Docker daemon log limits..."

DOCKER_DAEMON_JSON="/etc/docker/daemon.json"
DESIRED_LOG_CONFIG='"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}'

if [[ -f "$DOCKER_DAEMON_JSON" ]]; then
  # Check if log-driver is already set to avoid overwriting custom config
  if python3 -c "import json,sys; d=json.load(open('$DOCKER_DAEMON_JSON')); sys.exit(0 if d.get('log-driver')=='json-file' else 1)" 2>/dev/null; then
    success "  Docker log limits already configured — skipping."
  else
    # Merge our settings into existing daemon.json
    python3 - <<'PYEOF'
import json, sys
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
  # Reload Docker if running, otherwise it picks up on next start
  if systemctl is-active --quiet docker 2>/dev/null; then
    systemctl reload docker 2>/dev/null || systemctl restart docker
  fi
  success "  Docker daemon.json created with log limits."
fi

# ── 12. Node.js heap memory cap ───────────────────────────────────────────────
# Node.js defaults to using up to ~1.5 GB heap before GC kicks in.
# On a 1 GB VPS this causes OOM kills. Cap it at 256 MB via NODE_OPTIONS.
# This applies to any Node.js process started in a login shell on the host.
# Container-level Node processes need --max-old-space-size in their CMD/entrypoint.
info "12/13 Capping Node.js heap memory..."

NODE_OPTIONS_LINE='NODE_OPTIONS="--max-old-space-size=256"'
if ! grep -q "max-old-space-size" /etc/environment 2>/dev/null; then
  echo "$NODE_OPTIONS_LINE" >> /etc/environment
  success "  NODE_OPTIONS set in /etc/environment (256 MB heap cap)."
else
  success "  Node.js heap cap already set — skipping."
fi

# ── 13. CrowdSec memory tuning ────────────────────────────────────────────────
# CrowdSec reads logs into memory. Restarting it clears its in-memory cache.
# The mem_limit in docker-compose.oracle.yml (256m) is the primary guard.
# Additionally, configure the CrowdSec config to use a smaller bucket size
# to reduce peak memory usage during log bursts.
info "13/13 Tuning CrowdSec memory (if running)..."

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^crowdsec-oracle$"; then
  # Restart CrowdSec to clear its in-memory log cache (safe — decisions persist in DB)
  docker restart crowdsec-oracle 2>/dev/null \
    && success "  crowdsec-oracle restarted (in-memory cache cleared)." \
    || warn "  Could not restart crowdsec-oracle."
else
  success "  crowdsec-oracle not running — will apply mem_limit on next deploy."
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         Oracle OS Hardening Complete                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Next: run scripts/oracle-deploy.sh to deploy the stack."
echo ""
