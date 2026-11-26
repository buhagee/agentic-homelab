#!/usr/bin/env bash
# Host-level container healthcheck. Runs from a systemd timer as root.
# Silent on success; emails on missing, down, restarting or unhealthy services.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# shellcheck source=scripts/lib/platform-env.sh
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
# shellcheck source=scripts/lib/alert.sh
source "${PLATFORM_DIR}/scripts/lib/alert.sh"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "Usage: $0 [--dry-run]" >&2
      exit 2
      ;;
  esac
done

load_platform_env "$PLATFORM_DIR" || true

EXPECTED=(
  adguard cloudflared crawl4ai crowdsec
  homeassistant
  immich-machine-learning immich-postgres immich-redis immich-server
  mcp-academic-papers mcp-crawl4ai mcp-intervals mcp-searxng
  ollama
  paperless paperless-postgres paperless-redis scrutiny searxng
  traefik vaultwarden wireguard-home
)
OPTIONAL=(mcp-paperless)

declare -A STATUS=()
if ! docker_output="$(docker ps -a --format $'{{.Names}}\t{{.Status}}' 2>&1)"; then
  report="DOCKER_ERROR: ${docker_output:-docker ps failed}"
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '%s\n' "$report"
    exit 0
  fi
  printf '%s\n' "$report"
  send_alert "Qacey platform health alert" "$report" || true
  exit 1
fi

while IFS=$'\t' read -r name status; do
  [[ -n "$name" ]] && STATUS["$name"]="$status"
done <<< "$docker_output"

problems=()

check_status() {
  local name="$1"
  local status="$2"
  if [[ "$status" == *"unhealthy"* ]]; then
    problems+=("UNHEALTHY: $name ($status)")
  elif [[ "$status" == Restarting* ]]; then
    problems+=("RESTARTING: $name ($status)")
  elif [[ "$status" != Up* ]]; then
    problems+=("DOWN: $name ($status)")
  fi
}

for name in "${EXPECTED[@]}"; do
  status="${STATUS[$name]:-}"
  if [[ -z "$status" ]]; then
    problems+=("MISSING: $name")
  else
    check_status "$name" "$status"
  fi
done

for name in "${OPTIONAL[@]}"; do
  status="${STATUS[$name]:-}"
  [[ -z "$status" ]] && continue
  # Deliberately stopped optional services must not alert.
  [[ "$status" == Exited\ \(0\)* || "$status" == Created* ]] && continue
  check_status "$name" "$status"
done

if [[ ${#problems[@]} -eq 0 ]]; then
  exit 0
fi

report="$(printf '%s\n' "${problems[@]}")"

if [[ $DRY_RUN -eq 1 ]]; then
  printf '%s\n' "$report"
  exit 0
fi

printf '%s\n' "$report"
send_alert "Qacey platform health alert" "$report" || true
exit 1
