#!/usr/bin/env bash
# =============================================================================
# smoke-test.sh — Qacey Platform smoke tests
# =============================================================================
# Runs against the live deployment. Source .env first or pass QACEY_DOMAIN.
# Usage:
#   source .env && bash scripts/testing/smoke-test.sh
#   QACEY_DOMAIN=example.com bash scripts/testing/smoke-test.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load public config plus private secret overlay if not already sourced.
if [[ -z "${QACEY_DOMAIN:-}" ]]; then
  # shellcheck disable=SC1091
  source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
  load_platform_env "${PLATFORM_DIR}"
fi

DOMAIN="${QACEY_DOMAIN:-example.com}"
PASS=0; FAIL=0

GREEN='\033[0;32m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'

check() {
  local name="$1" url="$2"
  shift 2
  local expected_codes=("$@")
  local actual
  actual=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null || echo "000")
  for expected in "${expected_codes[@]}"; do
    if [[ "${actual}" == "${expected}" ]]; then
      echo -e "  ${GREEN}✅${NC} ${name} (${actual})"
      PASS=$((PASS+1))
      return
    fi
  done
  echo -e "  ${RED}❌${NC} ${name} — expected ${expected_codes[*]}, got ${actual}"
  FAIL=$((FAIL+1))
}

check_contains() {
  local name="$1" url="$2" pattern="$3"
  local body
  body=$(curl -sf --max-time 15 "${url}" 2>/dev/null || echo "")
  if echo "${body}" | grep -q "${pattern}"; then
    echo -e "  ${GREEN}✅${NC} ${name}"
    PASS=$((PASS+1))
  else
    echo -e "  ${RED}❌${NC} ${name} — pattern '${pattern}' not found"
    FAIL=$((FAIL+1))
  fi
}

echo ""
echo -e "${BLUE}── Phase 1: Infrastructure ──────────────────────────────────────${NC}"
check "Traefik cloudflared port"     "http://localhost:8080/"             "404"

echo ""
echo -e "${BLUE}── Phase 2: Services (U-02) ─────────────────────────────────────${NC}"

# Container running checks
for svc in immich-server immich-postgres immich-redis vaultwarden searxng mcp-searxng ollama; do
  STATE=$(docker inspect --format='{{.State.Status}}' "${svc}" 2>/dev/null || echo "missing")
  if [[ "${STATE}" == "running" ]]; then
    echo -e "  ${GREEN}✅${NC} U-02: ${svc} running"
    PASS=$((PASS+1))
  else
    echo -e "  ${RED}❌${NC} U-02: ${svc} running — got ${STATE}"
    FAIL=$((FAIL+1))
  fi
done

check_contains "Ollama embedding model API" \
  "http://127.0.0.1:11434/api/tags" \
  "nomic-embed-text"
# HTTP health checks — hit Traefik directly via local port to avoid DNS round-trip
# through Oracle. Uses the cloudflared entrypoint (:8080) with Host header.
for url_label in \
  "http://localhost:8080/api/server/ping|photos.${DOMAIN}|Immich ping|200" \
  "http://localhost:8080/|vault.${DOMAIN}|Vaultwarden home|200 302"
do
  url="${url_label%%|*}"; rest="${url_label#*|}"
  host="${rest%%|*}"; rest="${rest#*|}"
  label="${rest%%|*}"; codes="${rest##*|}"
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -H "Host: ${host}" "${url}" 2>/dev/null || echo "error")
  OK=false
  for code in $codes; do [[ "${STATUS}" == "${code}" ]] && OK=true; done
  if $OK; then
    echo -e "  ${GREEN}✅${NC} U-02: ${label} (${STATUS})"
    PASS=$((PASS+1))
  else
    echo -e "  ${RED}❌${NC} U-02: ${label} — got ${STATUS}"
    FAIL=$((FAIL+1))
  fi
done

# AdGuard Home
ADGUARD_URL="http://${HOME_SERVER_IP:-192.0.2.10}:3000"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$ADGUARD_URL" 2>/dev/null || echo "error")
if [[ "${STATUS}" == "200" ]] || [[ "${STATUS}" == "302" ]]; then
  echo -e "  ${GREEN}✅${NC} U-09: AdGuard Home web UI (${STATUS})"
  PASS=$((PASS+1))
else
  echo -e "  ${RED}❌${NC} U-09: AdGuard Home web UI — got ${STATUS}"
  FAIL=$((FAIL+1))
fi

echo ""
echo -e "${BLUE}── U-10: CrowdSec ───────────────────────────────────────────────${NC}"
for svc in crowdsec; do
  STATE=$(docker inspect --format='{{.State.Status}}' "${svc}" 2>/dev/null || echo "missing")
  if [[ "${STATE}" == "running" ]]; then
    echo -e "  ${GREEN}✅${NC} U-10: ${svc} running"
    PASS=$((PASS+1))
  else
    echo -e "  ${RED}❌${NC} U-10: ${svc} running — got ${STATE}"
    FAIL=$((FAIL+1))
  fi
done

# CrowdSec LAPI health
if docker exec crowdsec cscli version 2>/dev/null | grep -q "version" 2>/dev/null; then
  echo -e "  ${GREEN}✅${NC} U-10: CrowdSec LAPI responding"
  PASS=$((PASS+1))
else
  echo -e "  ${RED}❌${NC} U-10: CrowdSec LAPI not responding"
  FAIL=$((FAIL+1))
fi

# Bouncer registered
if docker exec crowdsec cscli bouncers list -o json 2>/dev/null | grep -q "traefik-bouncer" 2>/dev/null; then
  echo -e "  ${GREEN}✅${NC} U-10: traefik-bouncer registered"
  PASS=$((PASS+1))
else
  echo -e "  ${RED}❌${NC} U-10: traefik-bouncer not registered (set CROWDSEC_LAPI_KEY and restart)"
  FAIL=$((FAIL+1))
fi

echo ""
echo "────────────────────────────────────────────────────────────────"
echo -e "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo ""

[[ "${FAIL}" -eq 0 ]] && exit 0 || exit 1
