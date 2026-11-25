#!/usr/bin/env bash
# =============================================================================
# first-time-setup.sh — Qacey Platform first-time setup  ⚠️  RUN ONCE ONLY
# =============================================================================
# Runs from qacey-platform directory:
#   - Creates Docker networks
#   - Generates secrets and writes .env file
#   - Creates required host directories
#   - Sets up Hermes Agent service account + data volumes
#   - Starts all services via docker compose
#   - Pre-warms TLS certificates
#
# ⚠️  DO NOT re-run on an initialised instance — it regenerates secrets and
#    overwrites .env files, breaking all running services. Use reset.sh first
#    if you need to start over, or use the individual scripts in scripts/ for
#    specific post-deploy tasks (setup-oauth.sh, etc.)
# =============================================================================
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
HERMES_BASE_DIR="/mnt/ssd/qacey/hermes"
DEPLOY_AGENT_CONFIG_SCRIPT="${PLATFORM_DIR}/scripts/deploy/deploy-agent-config.sh"
START_SCRIPT="${PLATFORM_DIR}/scripts/start.sh"
SENTINEL="${PLATFORM_DIR}/.qacey-initialized"

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ "$(uname -s)" == "Linux" ]] || die "Must run on Linux."
[[ "${PWD}" != /mnt/c/* ]] || die "Do not run from Windows filesystem (/mnt/c/...). Use native Linux path."
command -v docker >/dev/null 2>&1 || die "Docker not found. Install Docker first."
command -v python3 >/dev/null 2>&1 || die "python3 not found."

if [[ -f "${SENTINEL}" ]]; then
  warn "Already initialised (.qacey-initialized exists). Run reset.sh first to start over."
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           Qacey Platform — First-Time Setup                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

info "Platform repo: ${PLATFORM_DIR}"


# ── Collect configuration ─────────────────────────────────────────────────────
echo ""
info "Collecting configuration..."
echo ""

# Domain
read -rp "  QACEY_DOMAIN [example.com]: " INPUT_DOMAIN
QACEY_DOMAIN="${INPUT_DOMAIN:-example.com}"

# Detect prod vs dev
if [[ "${QACEY_DOMAIN}" == *"example.com"* ]]; then
  CERT_RESOLVER="cloudflare"
  info "  Detected prod domain — using Cloudflare DNS-01 certs."
  read -rp "  CLOUDFLARE_TUNNEL_TOKEN: " CLOUDFLARE_TUNNEL_TOKEN
  [[ -n "${CLOUDFLARE_TUNNEL_TOKEN}" ]] || die "CLOUDFLARE_TUNNEL_TOKEN is required for prod."
  read -rp "  CF_DNS_API_TOKEN: " CF_DNS_API_TOKEN
  [[ -n "${CF_DNS_API_TOKEN}" ]] || die "CF_DNS_API_TOKEN is required for prod."
  DESEC_TOKEN=""
else
  CERT_RESOLVER="letsencrypt"
  info "  Detected dev domain — using deSEC DNS-01 certs."
  read -rp "  DESEC_TOKEN: " DESEC_TOKEN
  [[ -n "${DESEC_TOKEN}" ]] || die "DESEC_TOKEN is required for dev."
  CLOUDFLARE_TUNNEL_TOKEN=""
  CF_DNS_API_TOKEN=""
fi

read -rp "  ACME_EMAIL: " ACME_EMAIL
[[ -n "${ACME_EMAIL}" ]] || die "ACME_EMAIL is required."

read -rp "  ADMIN_USER [admin]: " INPUT_ADMIN_USER
ADMIN_USER="${INPUT_ADMIN_USER:-admin}"
read -rp "  ADMIN_EMAIL: " ADMIN_EMAIL
[[ -n "${ADMIN_EMAIL}" ]] || die "ADMIN_EMAIL is required."

while true; do
  read -rsp "  ADMIN_PASSWORD: " ADMIN_PASSWORD; echo ""
  # Validate: min 8 chars, at least 1 upper, 1 lower, 1 digit or special
  if [[ ${#ADMIN_PASSWORD} -ge 8 ]] \
    && echo "${ADMIN_PASSWORD}" | grep -q '[A-Z]' \
    && echo "${ADMIN_PASSWORD}" | grep -q '[a-z]' \
    && echo "${ADMIN_PASSWORD}" | grep -qE '[0-9!@#$%^&*()_+\-=]'; then
    break
  fi
  warn "Password must be ≥8 chars with at least 1 uppercase, 1 lowercase, 1 digit or special char."
done

# ── Generate secrets ──────────────────────────────────────────────────────────
info "Generating secrets..."

gen_hex()    { openssl rand -hex "$1"; }
gen_b64()    { openssl rand -base64 "$1"; }

VAULTWARDEN_ADMIN_TOKEN="$(gen_hex 32)"


# ── U-02 secrets ──────────────────────────────────────────────────────────
# Preserve existing values on re-run (idempotent secret generation)
prev_val() {
  local key="$1"
  local env_file
  for env_file in "${PLATFORM_DIR}/secrets/.env" "${PLATFORM_DIR}/.env"; do
    if [[ -f "$env_file" ]]; then
      local value
      value=$(grep "^${key}=" "$env_file" | cut -d= -f2- || true)
      if [[ -n "$value" ]]; then
        printf '%s' "$value"
        return
      fi
    fi
  done
}

IMMICH_DB_PASSWORD="$(prev_val IMMICH_DB_PASSWORD)"
[[ -z "${IMMICH_DB_PASSWORD}" ]] && IMMICH_DB_PASSWORD="$(gen_hex 24)"

MNEMO_POSTGRES_PASSWORD="$(prev_val MNEMO_POSTGRES_PASSWORD)"
[[ -z "${MNEMO_POSTGRES_PASSWORD}" ]] && MNEMO_POSTGRES_PASSWORD="$(gen_hex 24)"

SEARXNG_SECRET_KEY="$(prev_val SEARXNG_SECRET_KEY)"
[[ -z "${SEARXNG_SECRET_KEY}" ]] && SEARXNG_SECRET_KEY="$(gen_hex 32)"

OPENCODE_PASSWORD="$(prev_val OPENCODE_PASSWORD)"
[[ -z "${OPENCODE_PASSWORD}" ]] && OPENCODE_PASSWORD="$(gen_hex 32)"

CRAWL4AI_API_TOKEN="$(prev_val CRAWL4AI_API_TOKEN)"
[[ -z "${CRAWL4AI_API_TOKEN}" ]] && CRAWL4AI_API_TOKEN="$(gen_hex 32)"

# ── U-10: CrowdSec LAPI key ───────────────────────────────────────────────
CROWDSEC_LAPI_KEY="$(prev_val CROWDSEC_LAPI_KEY)"
[[ -z "${CROWDSEC_LAPI_KEY}" ]] && CROWDSEC_LAPI_KEY="$(gen_hex 32)"
CROWDSEC_ENROLLMENT_TOKEN="$(prev_val CROWDSEC_ENROLLMENT_TOKEN)"
success "Secrets generated."

# ── Collect platform alert and Hermes credentials ────────────────────────────
info "=== Platform Alert and Hermes Setup ==="
echo ""
read -rp  "  Alert recipient email: " ALERT_EMAIL_TO
[[ -n "${ALERT_EMAIL_TO}" ]] || die "ALERT_EMAIL_TO is required for platform alerts."
read -rp  "  Alert sender email (Google Workspace): " ALERT_EMAIL_FROM
[[ -n "${ALERT_EMAIL_FROM}" ]] || die "ALERT_EMAIL_FROM is required."
read -rp  "  SMTP username (usually the sender address): " SMTP_USER
[[ -n "${SMTP_USER}" ]] || die "SMTP_USER is required."
read -rsp "  SMTP app password: " SMTP_PASSWORD; echo ""
[[ -n "${SMTP_PASSWORD}" ]] || die "SMTP_PASSWORD is required."
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_ENCRYPTION=starttls
read -rsp "  OpenRouter API key (openrouter.ai/keys): " OPENROUTER_API_KEY; echo ""
[[ -n "${OPENROUTER_API_KEY}" ]] || die "OPENROUTER_API_KEY is required."

HERMES_API_KEY_JUSTIN="$(gen_hex 32)"
HERMES_API_KEY_ANNIQUE="$(gen_hex 32)"

command -v htpasswd >/dev/null 2>&1 || die "htpasswd not found. Install with: sudo apt install apache2-utils"
read -rsp "  Hermes dashboard password: " HERMES_DASH_PASS; echo ""
[[ -n "${HERMES_DASH_PASS}" ]] || die "Dashboard password is required."
HERMES_DASHBOARD_AUTH="$(echo "$(htpasswd -nb "${ADMIN_USER}" "${HERMES_DASH_PASS}")" | sed -e 's/\$/\$\$/g')"

success "Hermes credentials collected."

# Generate sandbox OAuth cookie secret once; it belongs in secrets/.env.
SANDBOX_OAUTH2_COOKIE_SECRET="$(prev_val SANDBOX_OAUTH2_COOKIE_SECRET)"
[[ -n "$SANDBOX_OAUTH2_COOKIE_SECRET" ]] || SANDBOX_OAUTH2_COOKIE_SECRET="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')"

# ── Write public platform .env ────────────────────────────────────────────────
info "Writing ${PLATFORM_DIR}/.env ..."
cat > "${PLATFORM_DIR}/.env" <<EOF
# Generated by first-time-setup.sh — $(date -u +%Y-%m-%dT%H:%M:%SZ)
PLATFORM_DIR=${PLATFORM_DIR}

QACEY_DOMAIN=${QACEY_DOMAIN}
CERT_RESOLVER=${CERT_RESOLVER}
ACME_EMAIL=${ACME_EMAIL}
ADMIN_USER=${ADMIN_USER}
ADMIN_EMAIL=${ADMIN_EMAIL}
HOME_SERVER_IP=$(prev_val HOME_SERVER_IP)
ORACLE_IP=$(prev_val ORACLE_IP)
TRAEFIK_PROXY_IP=$(prev_val TRAEFIK_PROXY_IP)
GOOGLE_CLIENT_ID=$(prev_val GOOGLE_CLIENT_ID)
VAULTWARDEN_SSO_ENABLED=$(prev_val VAULTWARDEN_SSO_ENABLED)

# ── Hermes runtime configuration ───────────────────────────────────────────
HERMES_UID=
HERMES_GID=
ALERT_EMAIL_TO=${ALERT_EMAIL_TO}
ALERT_EMAIL_FROM=${ALERT_EMAIL_FROM}
SMTP_HOST=${SMTP_HOST}
SMTP_PORT=${SMTP_PORT}
SMTP_USER=${SMTP_USER}
SMTP_ENCRYPTION=${SMTP_ENCRYPTION}
SANDBOX_WORKSPACE_DIR=/mnt/ssd/qacey/hermes/justin/data/sandbox
HERMES_PROVIDER=opencode-go
HERMES_PROVIDER_BASE_URL=https://openrouter.ai/api/v1
HERMES_MODEL=deepseek-v4-pro
HERMES_MODEL_FALLBACK=deepseek-v4-flash
HERMES_FALLBACK_PROVIDER=opencode-go
HERMES_FALLBACK_BASE_URL=
HERMES_FALLBACK_KEY_ENV=
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1
HERMES_REASONING_EFFORT=high
HERMES_IMAGE_INPUT_MODE=text
HERMES_VISION_MODEL=google/gemini-2.5-flash
HERMES_IMAGE_GEN_MODEL=google/gemini-2.5-flash-image
HERMES_IMAGE_GEN_MAX_PARALLEL_REQUESTS=4
B2_ACCOUNT_ID=$(prev_val B2_ACCOUNT_ID)
B2_BUCKET=$(prev_val B2_BUCKET)
EOF
chmod 600 "${PLATFORM_DIR}/.env"
success "Platform .env written."

# ── Write private secrets overlay ────────────────────────────────────────────
info "Writing ${PLATFORM_DIR}/secrets/.env ..."
sudo mkdir -p "${PLATFORM_DIR}/secrets"
cat > "${PLATFORM_DIR}/secrets/.env" <<EOF
# Generated by first-time-setup.sh — private secrets; do not commit.
CLOUDFLARE_TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
CF_DNS_API_TOKEN=${CF_DNS_API_TOKEN}
DESEC_TOKEN=${DESEC_TOKEN}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
GOOGLE_CLIENT_SECRET=$(prev_val GOOGLE_CLIENT_SECRET)
VAULTWARDEN_ADMIN_TOKEN=${VAULTWARDEN_ADMIN_TOKEN}
IMMICH_DB_PASSWORD=${IMMICH_DB_PASSWORD}
IMMICH_API_KEY=$(prev_val IMMICH_API_KEY)
SEARXNG_SECRET_KEY=${SEARXNG_SECRET_KEY}
INTERVALS_API_KEY_JUSTIN=$(prev_val INTERVALS_API_KEY_JUSTIN)
PAPER_SEARCH_MCP_CORE_API_KEY=$(prev_val PAPER_SEARCH_MCP_CORE_API_KEY)
OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
OPENCODE_GO_API_KEY=$(prev_val OPENCODE_GO_API_KEY)
OPENCODE_PASSWORD=${OPENCODE_PASSWORD}
CRAWL4AI_API_TOKEN=${CRAWL4AI_API_TOKEN}
SMTP_PASSWORD=${SMTP_PASSWORD}
HERMES_API_KEY_JUSTIN=${HERMES_API_KEY_JUSTIN}
HERMES_API_KEY_ANNIQUE=${HERMES_API_KEY_ANNIQUE}
HERMES_DASHBOARD_AUTH=${HERMES_DASHBOARD_AUTH}
SANDBOX_OAUTH2_COOKIE_SECRET=${SANDBOX_OAUTH2_COOKIE_SECRET}
MNEMO_POSTGRES_PASSWORD=${MNEMO_POSTGRES_PASSWORD}
HA_LONG_LIVED_TOKEN=$(prev_val HA_LONG_LIVED_TOKEN)
GOOGLE_WORKSPACE_CLIENT_ID=$(prev_val GOOGLE_WORKSPACE_CLIENT_ID)
GOOGLE_WORKSPACE_CLIENT_SECRET=$(prev_val GOOGLE_WORKSPACE_CLIENT_SECRET)
GOOGLE_WORKSPACE_REFRESH_TOKEN_JUSTIN=$(prev_val GOOGLE_WORKSPACE_REFRESH_TOKEN_JUSTIN)
GOOGLE_WORKSPACE_REFRESH_TOKEN_ANNIQUE=$(prev_val GOOGLE_WORKSPACE_REFRESH_TOKEN_ANNIQUE)
HERMES_WORKSPACE_GOOGLE_CLIENT_SECRET=$(prev_val HERMES_WORKSPACE_GOOGLE_CLIENT_SECRET)
HERMES_WORKSPACE_SESSION_SECRET=$(prev_val HERMES_WORKSPACE_SESSION_SECRET)
CROWDSEC_LAPI_KEY=${CROWDSEC_LAPI_KEY}
CROWDSEC_ENROLLMENT_TOKEN=${CROWDSEC_ENROLLMENT_TOKEN}
WIREGUARD_HOME_PRIVATE_KEY=$(prev_val WIREGUARD_HOME_PRIVATE_KEY)
B2_ACCOUNT_KEY=$(prev_val B2_ACCOUNT_KEY)
RESTIC_PASSWORD=$(prev_val RESTIC_PASSWORD)
EOF
chmod 600 "${PLATFORM_DIR}/secrets/.env"
success "Private secrets overlay written."

# ── U-04: Hermes service account + data directories ──────────────────────────
info "Setting up Hermes service account..."
if ! id hermes &>/dev/null; then
  sudo useradd --system --no-create-home --shell /bin/false hermes
  success "Created 'hermes' system account."
else
  info "  'hermes' account already exists — skipping."
fi
# Identify the deploying user (works whether script is run directly or via sudo)
DEPLOY_USER="${SUDO_USER:-$USER}"
# Runtime files are owner-only. Run Hermes as the deploying user that owns its
# mounted data; retain the dedicated hermes group for shared skill access.
HERMES_UID="$(id -u "$DEPLOY_USER")"
HERMES_GID="$(id -g hermes)"

sudo mkdir -p \
  "${HERMES_BASE_DIR}/justin/data" "${HERMES_BASE_DIR}/justin/home" \
  "${HERMES_BASE_DIR}/annique/data" "${HERMES_BASE_DIR}/annique/home"
# buhagiar (or whoever deploys) owns the dirs; hermes group for container access
sudo chown -R "${DEPLOY_USER}:hermes" "${HERMES_BASE_DIR}"
# 770: deploy user has full access; hermes containers (gid hermes) have full access
sudo chmod -R 770 "${HERMES_BASE_DIR}"
success "Hermes data directories created."

# U-07: Skill volumes (hermes owns directly — agents read/write skills)
sudo mkdir -p "${HERMES_BASE_DIR}/skills/shared"
sudo mkdir -p "${HERMES_BASE_DIR}/skills/justin"
sudo mkdir -p "${HERMES_BASE_DIR}/skills/annique"
sudo chown -R hermes:hermes "${HERMES_BASE_DIR}/skills"
sudo find "${HERMES_BASE_DIR}/skills" -type d -exec chmod 750 {} +
sudo find "${HERMES_BASE_DIR}/skills" -type f ! -perm /111 -exec chmod 640 {} +
sudo find "${HERMES_BASE_DIR}/skills" -type f -perm /111 -exec chmod 750 {} +
success "Hermes skill directories created."

# Seed config.yaml for each user (no sudo needed — deploying user owns the dirs)
for USER_DIR in "${HERMES_BASE_DIR}/justin/data" "${HERMES_BASE_DIR}/annique/data"; do
  if [[ ! -f "${USER_DIR}/config.yaml" ]]; then
    tee "${USER_DIR}/config.yaml" > /dev/null <<'YAML'
terminal:
  backend: local
approvals:
  mode: smart
  timeout: 60
privacy:
  redact_pii: true
security:
  allow_private_urls: false
  redact_secrets: true
  tirith_enabled: true
  tirith_fail_open: false
sessions:
  auto_prune: true
  retention_days: 400
  write_json_snapshots: false
YAML
  fi
done
success "Hermes config.yaml seeded."

# Patch HERMES_UID/GID back into .env now that we know them
sed -i "s|^HERMES_UID=$|HERMES_UID=${HERMES_UID}|" "${PLATFORM_DIR}/.env"
sed -i "s|^HERMES_GID=$|HERMES_GID=${HERMES_GID}|" "${PLATFORM_DIR}/.env"

# Deploy MCP configs + persona files
info "Deploying Hermes MCP configs and persona files..."
[[ -f "${DEPLOY_AGENT_CONFIG_SCRIPT}" ]] || die "Missing deploy script: ${DEPLOY_AGENT_CONFIG_SCRIPT}"
bash "${DEPLOY_AGENT_CONFIG_SCRIPT}"
success "Hermes agent config deployed."

# ── Create host directories ───────────────────────────────────────────────────
info "Creating host directories..."
sudo mkdir -p /opt/qacey/traefik/certs
sudo touch /opt/qacey/traefik/certs/acme.json
sudo chmod 600 /opt/qacey/traefik/certs/acme.json

# ── U-08: Home Assistant data directory + trusted proxy config ───────────────
sudo mkdir -p /opt/qacey/homeassistant/config
# Write base configuration.yaml with trusted_proxies for Traefik reverse proxy.
# Only write if it doesn't already exist (preserve any existing HA config).
HA_CONFIG="/opt/qacey/homeassistant/config/configuration.yaml"
if [[ ! -f "$HA_CONFIG" ]]; then
  sudo tee "$HA_CONFIG" > /dev/null << HACFG
# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

homeassistant:
  external_url: "https://ha.${QACEY_DOMAIN}"
  internal_url: "http://localhost:8123"

http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 172.16.0.0/12   # Docker bridge networks (Traefik)
    - 127.0.0.1

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml
HACFG
  success "Home Assistant configuration.yaml written."
else
  warn "Home Assistant configuration.yaml already exists — skipping."
fi

# ── U-08: UFW rules for Home Assistant (Docker → host port 8123) ─────────────
if command -v ufw &>/dev/null && sudo ufw status | grep -q "Status: active"; then
  info "Adding UFW rules for Home Assistant (Docker → port 8123)..."
  sudo ufw allow from 172.16.0.0/12 to any port 8123 comment "Docker networks → Home Assistant" 2>/dev/null || true
  success "UFW rules for port 8123 added."
fi

# ── U-10: CrowdSec data directories ─────────────────────────────────────────
sudo mkdir -p /opt/qacey/crowdsec/config
sudo mkdir -p /opt/qacey/crowdsec/data
sudo mkdir -p /opt/qacey/traefik/logs
sudo touch /opt/qacey/traefik/logs/access.log

success "Host directories created."

# ── Create Docker networks ────────────────────────────────────────────────────
info "Creating Docker networks..."
docker network create qacey-proxy    2>/dev/null && success "Created qacey-proxy."    || warn "qacey-proxy already exists."
docker network create qacey-internal 2>/dev/null && success "Created qacey-internal." || warn "qacey-internal already exists."
docker network create qacey-opencode 2>/dev/null && success "Created qacey-opencode." || warn "qacey-opencode already exists."

# ── Validate compose config ───────────────────────────────────────────────────
info "Validating docker compose config..."
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
set_platform_compose_env_args "${PLATFORM_DIR}"
docker compose \
  -f "${PLATFORM_DIR}/docker-compose.platform.yml" \
  "${COMPOSE_ENV_ARGS[@]}" \
  config --quiet
success "Compose config valid."

# ── Start services ────────────────────────────────────────────────────────────
info "Starting all services (this may take a few minutes for first pull)..."
[[ -f "${START_SCRIPT}" ]] || die "Missing start script: ${START_SCRIPT}"
bash "${START_SCRIPT}"
success "Services started."

# ── U-12: Register CrowdSec Traefik bouncer (maxlerebourg plugin) ─────────────
# The plugin runs inside Traefik (no separate container). Key must be registered
# with the CrowdSec LAPI so the plugin can authenticate.
# BOUNCER_KEY_<name> env var is not supported in CrowdSec v1.6.x with hyphens.
# Register explicitly; key is persisted in /opt/qacey/crowdsec/config.
info "Registering CrowdSec Traefik bouncer..."
if docker exec crowdsec cscli bouncers list 2>/dev/null | grep -q "traefik-bouncer"; then
  info "traefik-bouncer already registered, skipping."
else
  MAX_CS=30; WAITED=0
  until docker exec crowdsec cscli version >/dev/null 2>&1; do
    sleep 2; WAITED=$((WAITED+2))
    [[ ${WAITED} -lt ${MAX_CS} ]] || { warn "CrowdSec LAPI not ready — bouncer registration skipped. Run manually: docker exec crowdsec cscli bouncers add traefik-bouncer --key \$CROWDSEC_LAPI_KEY"; break; }
  done
  if docker exec crowdsec cscli version >/dev/null 2>&1; then
    docker exec crowdsec cscli bouncers add traefik-bouncer --key "${CROWDSEC_LAPI_KEY}" \
      && success "traefik-bouncer registered." \
      || warn "Bouncer registration failed — run manually: docker exec crowdsec cscli bouncers add traefik-bouncer --key \$CROWDSEC_LAPI_KEY"
  fi
fi

# Install AppSec collections (U-12)
info "Installing CrowdSec AppSec collections..."
if docker exec crowdsec cscli version >/dev/null 2>&1; then
  docker exec crowdsec cscli collections install \
    crowdsecurity/appsec-virtual-patching \
    crowdsecurity/appsec-generic-rules 2>/dev/null \
    && success "AppSec collections installed." \
    || warn "AppSec collection install failed — run manually after start."
fi

# ── U-10: CrowdSec cloud enrollment ─────────────────────────────────────────
if [[ -n "${CROWDSEC_ENROLLMENT_TOKEN:-}" ]]; then
  info "Enrolling CrowdSec with cloud console..."
  docker exec crowdsec cscli console enroll "${CROWDSEC_ENROLLMENT_TOKEN}" \
    && docker exec crowdsec cscli console enable community-blocklist \
    && docker restart crowdsec \
    && success "CrowdSec cloud enrollment complete." \
    || warn "CrowdSec enrollment failed — run manually: docker exec crowdsec cscli console enroll \$CROWDSEC_ENROLLMENT_TOKEN"
else
  info "CROWDSEC_ENROLLMENT_TOKEN not set — skipping cloud enrollment."
fi

# ── Pre-warm TLS certs ────────────────────────────────────────────────────────
info "Pre-warming TLS certificates (up to 5 min)..."
MAX_TLS=300; WAITED=0
until curl -sf "https://agent.${QACEY_DOMAIN}/" >/dev/null 2>&1 || \
      curl -sf -o /dev/null -w "%{http_code}" "https://agent.${QACEY_DOMAIN}/" 2>/dev/null | grep -qE "^(200|401|403)"; do
  sleep 10; WAITED=$((WAITED+10))
  [[ ${WAITED} -lt ${MAX_TLS} ]] || { warn "TLS cert not ready after ${MAX_TLS}s — check Traefik logs."; break; }
  echo -n "."
done
echo ""
[[ ${WAITED} -lt ${MAX_TLS} ]] && success "TLS certificates ready."

# ── Baby Buddy: promote admin user to staff/superuser ────────────────────────
# oauth2-proxy creates Django users with Google's numeric ID as the username.
# By default these are non-staff — they can log in but cannot add children or
# create entries. We wait for Baby Buddy to be ready then promote BABY_ADMIN_EMAIL.
BABY_ADMIN_EMAIL="${BABY_ADMIN_EMAIL:-${ADMIN_EMAIL:-}}"
if [[ -n "${BABY_ADMIN_EMAIL}" ]]; then
  info "Waiting for Baby Buddy to be ready..."
  MAX_WAIT=60; WAITED=0
  until docker exec babybuddy curl -sf http://localhost:8000/ >/dev/null 2>&1; do
    sleep 3; WAITED=$((WAITED+3))
    [[ ${WAITED} -lt ${MAX_WAIT} ]] || { warn "Baby Buddy not ready — skipping staff promotion. Run scripts/setup-babybuddy-admin.sh manually after first login."; break; }
    echo -n "."
  done
  echo ""
  # NOTE: the user record is only created on first login, so we can't promote
  # here — we emit a reminder instead. The user must log in first.
  warn "Baby Buddy: after your first login at https://baby.${QACEY_DOMAIN},"
  warn "run:  bash scripts/setup-babybuddy-admin.sh ${BABY_ADMIN_EMAIL}"
  warn "This grants full staff/superuser access (required to add children and entries)."
fi

# ── Mark initialised ─────────────────────────────────────────────────────────
touch "${SENTINEL}"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  Setup Complete!                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Dashboard: https://agent.${QACEY_DOMAIN}  (basic auth: ${ADMIN_USER})"
echo ""
echo "  ── Siri Shortcuts API keys (save these!) ────────────────────"
echo "  Justin:  ${HERMES_API_KEY_JUSTIN}"
echo "  Annique: ${HERMES_API_KEY_ANNIQUE}"
echo ""
echo "  ── Siri Shortcuts API endpoints ─────────────────────────────"
echo "  Justin:  https://api-justin.${QACEY_DOMAIN}"
echo "  Annique: https://api-annique.${QACEY_DOMAIN}"
echo ""
echo "  ── U-02: Google OAuth redirect URIs ─────────────────────────"
echo "  Register these at console.cloud.google.com → APIs & Services → Credentials"
echo ""
info "Google OAuth redirect URIs to register:"
echo "   https://media.${QACEY_DOMAIN}/auth/login                           (Immich)"
echo "   https://baby.${QACEY_DOMAIN}/oauth2/callback                       (Baby Buddy)"
echo "   https://vault.${QACEY_DOMAIN}/identity/connect/oidc-signin         (Vaultwarden)"
echo ""
echo "  Next step: run scripts/smoke-test.sh to verify."
echo ""
