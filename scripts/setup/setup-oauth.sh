#!/usr/bin/env bash
# =============================================================================
# setup-oauth.sh — Configure Google OAuth for Immich
# =============================================================================
# Run once after first deploy. Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
# to be set in .env.
#
# What this script does:
#   1. Creates the Immich admin account (first user = admin)
#   2. Configures Google OAuth in Immich via API
#   3. Disables password login and restricts self-registration
#   5. Prints browser OAuth callback/allowlist guidance
#
# Re-runnable: yes. Uses IMMICH_API_KEY from .env on re-runs (when password
# login is disabled). Generate one at: Immich → Account Settings → API Keys.
#
# Usage:
#   bash scripts/setup-oauth.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load public config plus private secret overlay.
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
load_platform_env "${PLATFORM_DIR}"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Validate required vars ────────────────────────────────────────────────────
DOMAIN="${QACEY_DOMAIN:-example.com}"
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

[[ -z "${GOOGLE_CLIENT_ID}" ]]     && { error "GOOGLE_CLIENT_ID not set in .env"; exit 1; }
[[ -z "${GOOGLE_CLIENT_SECRET}" ]] && { error "GOOGLE_CLIENT_SECRET not set in .env"; exit 1; }
[[ -z "${ADMIN_EMAIL}" ]]          && { error "ADMIN_EMAIL not set in .env"; exit 1; }
[[ -z "${ADMIN_PASSWORD}" ]]       && { error "ADMIN_PASSWORD not set in .env"; exit 1; }

IMMICH_URL="https://photos.${DOMAIN}"
IMMICH_API_KEY="${IMMICH_API_KEY:-}"

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Qacey OAuth Setup — Google OAuth for Immich  ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ── Helper: wait for service ──────────────────────────────────────────────────
wait_for() {
  local name="$1" url="$2" max="${3:-30}"
  info "Waiting for ${name} to be ready..."
  for i in $(seq 1 "${max}"); do
    if curl -sf --max-time 5 "${url}" > /dev/null 2>&1; then
      success "${name} is ready"
      return 0
    fi
    sleep 2
  done
  error "${name} not ready after $((max * 2))s"
  exit 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# IMMICH
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${BLUE}── Immich ───────────────────────────────────────────────────${NC}"

wait_for "Immich" "${IMMICH_URL}/api/server/ping"

# Step 1: Create admin account (first user = admin)
info "Creating Immich admin account (${ADMIN_EMAIL})..."
REGISTER_RESP=$(curl -s -X POST "${IMMICH_URL}/api/auth/admin-sign-up" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\",\"name\":\"Admin\"}" 2>/dev/null)

if echo "${REGISTER_RESP}" | grep -q '"id"'; then
  success "Admin account created"
elif echo "${REGISTER_RESP}" | grep -q "already"; then
  warn "Admin account already exists — continuing"
else
  # May already be set up — try logging in
  warn "Registration response: ${REGISTER_RESP}"
fi

# Step 2: Get auth token — prefer API key (works even when password login is off)
if [[ -n "${IMMICH_API_KEY}" ]]; then
  info "Using IMMICH_API_KEY from .env..."
  IMMICH_TOKEN=""
  IMMICH_AUTH_HEADER="x-api-key: ${IMMICH_API_KEY}"
  # Verify the key works
  CHECK=$(curl -s "${IMMICH_URL}/api/users/me" -H "${IMMICH_AUTH_HEADER}" 2>/dev/null)
  if echo "${CHECK}" | grep -q '"email"'; then
    success "Authenticated via API key"
  else
    error "IMMICH_API_KEY is set but invalid. Response: ${CHECK}"
    exit 1
  fi
else
  info "Logging in to Immich (password)..."
  LOGIN_RESP=$(curl -s -X POST "${IMMICH_URL}/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" 2>/dev/null)

  IMMICH_TOKEN=$(echo "${LOGIN_RESP}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('accessToken',''))" 2>/dev/null)

  if [[ -z "${IMMICH_TOKEN}" ]]; then
    error "Failed to get Immich auth token. Response: ${LOGIN_RESP}"
    error "If password login is already disabled, set IMMICH_API_KEY in .env"
    error "Generate one at: ${IMMICH_URL} → Account Settings → API Keys"
    exit 1
  fi
  IMMICH_AUTH_HEADER="Authorization: Bearer ${IMMICH_TOKEN}"
  success "Logged in to Immich"
fi

# Step 3: Get current system config
info "Fetching current Immich system config..."
CURRENT_CONFIG=$(curl -s "${IMMICH_URL}/api/system-config" \
  -H "${IMMICH_AUTH_HEADER}" 2>/dev/null)

# Step 4: Merge OAuth config into current config
info "Configuring Google OAuth in Immich..."
# Write the python script to a temp file to avoid heredoc/variable quoting issues
TMPPY=$(mktemp /tmp/immich-oauth-XXXXXX.py)
cat > "${TMPPY}" <<'PYEOF'
import json, sys, os

current = json.loads(sys.stdin.read())

ios_client_id = os.environ.get("GOOGLE_IOS_CLIENT_ID", "")

# Merge OAuth config — preserve existing fields, override key ones
current['oauth'].update({
    "enabled": True,
    "issuerUrl": "https://accounts.google.com",
    "clientId": os.environ["GOOGLE_CLIENT_ID"],
    "clientSecret": os.environ["GOOGLE_CLIENT_SECRET"],
    "scope": "openid email profile",
    "signingAlgorithm": "RS256",
    "storageLabelClaim": "preferred_username",
    "storageQuotaClaim": "immich_quota",
    "buttonText": "Sign in with Google",
    "autoRegister": False,   # Admin must pre-create accounts; OAuth links by email
    "autoLaunch": False,
    # Mobile override — uses Immich's built-in forwarding endpoint which redirects
    # to app.immich:///oauth-callback (required since Google blocks custom schemes on web clients)
    "mobileOverrideEnabled": True,
    "mobileRedirectUri": "https://photos." + os.environ["QACEY_DOMAIN"] + "/api/oauth/mobile-redirect"
})

# Disable password login — OAuth only
current['passwordLogin']['enabled'] = False

print(json.dumps(current))
PYEOF

OAUTH_CONFIG=$(echo "${CURRENT_CONFIG}" | python3 "${TMPPY}")
rm -f "${TMPPY}"

UPDATE_RESP=$(curl -s -X PUT "${IMMICH_URL}/api/system-config" \
  -H "${IMMICH_AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d "${OAUTH_CONFIG}" 2>/dev/null)

if echo "${UPDATE_RESP}" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('oauth',{}).get('enabled') else 1)" 2>/dev/null; then
  success "Google OAuth configured in Immich"
else
  error "Failed to configure Immich OAuth. Response: ${UPDATE_RESP}"
  exit 1
fi

# Step 5: Offer to delete bootstrap admin
# NOTE: Immich does not allow deleting your own account via API.
# The workflow is: log in via Google OAuth first (which auto-registers you),
# then log back in as the bootstrap admin and delete it — OR use the web UI.
info "Fetching Immich admin user ID..."
ADMIN_USER=$(curl -s "${IMMICH_URL}/api/admin/users" \
  -H "${IMMICH_AUTH_HEADER}" 2>/dev/null | \
  python3 -c "
import sys, json
users = json.load(sys.stdin)
for u in users:
    if u.get('email') == '${ADMIN_EMAIL}':
        print(u['id'])
        break
" 2>/dev/null) || true

if [[ -n "${ADMIN_USER}" ]]; then
  warn "Bootstrap admin user ID: ${ADMIN_USER}"
  warn "Immich does not allow deleting your own account via API."
  warn ""
  warn "To recreate the platform admin via Google OAuth:"
  warn "  1. Go to ${IMMICH_URL} and click 'Sign in with Google'"
  warn "     → This auto-registers your Google account as a new user"
  warn "  2. Log back in as the bootstrap admin (${ADMIN_EMAIL} / password)"
  warn "  3. Go to Administration → Users → promote your Google account to admin"
  warn "  4. Log out, log back in as your Google account"
  warn "  5. Delete the bootstrap admin from Administration → Users"
  warn ""
  warn "Or run this after step 3 to delete via API (using a fresh token):"
  warn "  TOKEN=\$(curl -s -X POST ${IMMICH_URL}/api/auth/login \\"
  warn "    -H 'Content-Type: application/json' \\"
  warn "    -d '{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}' \\"
  warn "    | python3 -c \"import sys,json; print(json.load(sys.stdin)['accessToken'])\")"
  warn "  curl -X DELETE '${IMMICH_URL}/api/admin/users/${ADMIN_USER}?force=true' \\"
  warn "    -H \"Authorization: Bearer \${TOKEN}\""
fi

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BLUE}── Summary ──────────────────────────────────────────────────${NC}"
echo ""
echo -e "  ${GREEN}Google OAuth redirect URIs to register in Google Cloud Console:${NC}"
echo -e "  console.cloud.google.com → APIs & Services → Credentials → OAuth 2.0 Client"
echo ""
echo -e "  https://photos.${DOMAIN}/auth/login                           (Immich)"
echo -e "  https://photos.${DOMAIN}/api/oauth/mobile-redirect            (Immich iOS)"
  echo -e "  https://sandbox.${DOMAIN}/oauth2/callback                     (Temporary sandbox via oauth2-proxy)"
echo -e "  https://vault.${DOMAIN}/identity/connect/oidc-signin          (Vaultwarden)"
echo ""
success "OAuth setup complete"
echo ""
