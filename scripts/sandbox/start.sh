#!/usr/bin/env bash
# Start the isolated, agent-editable sandbox service.
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WORKSPACE_DIR="${SANDBOX_WORKSPACE_DIR:-/mnt/ssd/qacey/hermes/justin/data/sandbox}"

[[ -f "${PLATFORM_DIR}/.env" ]] || { echo "Missing ${PLATFORM_DIR}/.env" >&2; exit 1; }
[[ -d "${WORKSPACE_DIR}" ]] || { echo "Missing sandbox workspace: ${WORKSPACE_DIR}" >&2; exit 1; }
# shellcheck source=scripts/lib/allowlist.sh
source "${PLATFORM_DIR}/scripts/lib/allowlist.sh"
require_allowlist "${PLATFORM_DIR}"

oauth_secret_present=0
google_client_id_present=0
google_client_secret_present=0
[[ -n "${SANDBOX_OAUTH2_COOKIE_SECRET:-}" ]] && oauth_secret_present=1
[[ -n "${GOOGLE_CLIENT_ID:-}" ]] && google_client_id_present=1
[[ -n "${GOOGLE_CLIENT_SECRET:-}" ]] && google_client_secret_present=1
for env_file in "${PLATFORM_DIR}/.env" "${PLATFORM_DIR}/secrets/.env"; do
  if [[ -f "$env_file" ]]; then
    grep -Eq '^SANDBOX_OAUTH2_COOKIE_SECRET=[^[:space:]]' "$env_file" && oauth_secret_present=1
    grep -Eq '^GOOGLE_CLIENT_ID=[^[:space:]]' "$env_file" && google_client_id_present=1
    grep -Eq '^GOOGLE_CLIENT_SECRET=[^[:space:]]' "$env_file" && google_client_secret_present=1
  fi
done
[[ "$oauth_secret_present" == "1" ]] || {
  echo "SANDBOX_OAUTH2_COOKIE_SECRET is required in .env or secrets/.env." >&2
  echo "Generate it with: openssl rand -base64 32 | tr '+/' '-_' | tr -d '='" >&2
  exit 1
}
[[ "$google_client_id_present" == "1" && "$google_client_secret_present" == "1" ]] || {
  echo "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required in .env or secrets/.env." >&2
  exit 1
}

compose=(
  docker compose
  --project-name qacey-platform
  -f "${PLATFORM_DIR}/docker-compose.platform.yml"
  --env-file "${PLATFORM_DIR}/versions.env"
  --env-file "${PLATFORM_DIR}/.env"
)
if [[ -f "${PLATFORM_DIR}/secrets/.env" ]]; then
  compose+=(--env-file "${PLATFORM_DIR}/secrets/.env")
fi

# Traefik must join the sandbox edge network before it can discover the app.
"${compose[@]}" up -d --no-deps traefik
"${compose[@]}" --profile sandbox up -d --build hermes-sandbox-oauth2-proxy

echo "Sandbox started. Check: https://sandbox.${QACEY_DOMAIN:-example.com}"
echo "Agent workspace: /opt/data/sandbox"
echo "Google OAuth allowlist: secrets/browser-oauth-allowed-emails.txt"
