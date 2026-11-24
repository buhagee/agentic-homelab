#!/usr/bin/env bash
# =============================================================================
# smoke-test-api.sh — Verify Hermes peer API endpoints are reachable/responding
# =============================================================================
# Tests both Justin's and Annique's API servers (health + chat completion) from
# the opposite Hermes container. The API is intentionally not host/public-bound.
#
# Usage:
#   bash scripts/smoke-test-api.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass()  { echo -e "${GREEN}✓${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*"; FAILURES=$((FAILURES+1)); }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
FAILURES=0

ENV_FILE="$PLATFORM_DIR/.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing .env: $ENV_FILE"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker not found"; exit 1; }

# Load public config plus private secret overlay.
# shellcheck disable=SC1091
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
load_platform_env "${PLATFORM_DIR}"

QACEY_DOMAIN="${QACEY_DOMAIN:-}"
[[ -n "$QACEY_DOMAIN" ]] || { echo "QACEY_DOMAIN not set in .env"; exit 1; }

echo ""
echo "Hermes API Smoke Test — $(date)"
echo "Domain: $QACEY_DOMAIN"
echo "────────────────────────────────────────"

test_instance() {
  local name="$1"
  local probe_container="$2"
  local base_url="$3"
  local api_key="$4"

  echo ""
  echo "── $name ($base_url via $probe_container) ──"

  # Health check is intentionally unauthenticated inside the dedicated
  # hermes-peer network; shared qacey networks cannot reach this bind address.
  local health_status
  health_status=$(docker exec "$probe_container" \
    curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$base_url/health" \
    2>/dev/null || echo "000")
  if [[ "$health_status" == "200" ]]; then
    pass "/health → 200 OK"
  else
    fail "/health → $health_status (expected 200)"
    warn "  Is both Hermes containers running? Check: docker ps | grep hermes-"
    return
  fi

  # Chat completion (requires auth)
  if [[ -z "$api_key" ]]; then
    warn "/v1/chat/completions — skipped (no API key set)"
    return
  fi

  local response
  response=$(docker exec -e "HERMES_TEST_API_KEY=$api_key" "$probe_container" sh -lc \
    'curl -s --max-time 90 -X POST "$1/v1/chat/completions" \
      -H "Authorization: Bearer $HERMES_TEST_API_KEY" \
      -H "Content-Type: application/json" \
      -d '\''{"model":"hermes-agent","messages":[{"role":"user","content":"Reply with exactly the words: API test successful"}],"stream":false}'\'' \
      2>/dev/null' sh "$base_url" || echo "CURL_ERROR")

  if [[ "$response" == "CURL_ERROR" ]]; then
    fail "/v1/chat/completions → network error or timeout"
    return
  fi

  local content
  content=$(echo "$response" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])" \
    2>/dev/null || echo "")

  if [[ -n "$content" ]]; then
    pass "/v1/chat/completions → $content"
  else
    fail "/v1/chat/completions → unexpected response:"
    echo "    $response" | head -5
  fi
}

test_instance "Justin" \
  "hermes-annique" \
  "http://172.31.255.2:8642" \
  "${HERMES_API_KEY_JUSTIN:-}"

test_instance "Annique" \
  "hermes-justin" \
  "http://172.31.255.3:8642" \
  "${HERMES_API_KEY_ANNIQUE:-}"

echo ""
echo "────────────────────────────────────────"
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}All checks passed.${NC}"
  exit 0
else
  echo -e "${RED}$FAILURES check(s) failed.${NC}"
  exit 1
fi
