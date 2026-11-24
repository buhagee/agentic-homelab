#!/usr/bin/env bash
# restart-hermes.sh — Redeploy agent config and force-recreate hermes containers.
# Use this after any change to .env (model, tokens) or services/agent/ files.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck disable=SC1091
source "$PLATFORM_DIR/scripts/lib/platform-env.sh"
set_platform_compose_env_args "$PLATFORM_DIR"

echo "Deploying agent config..."
bash "$PLATFORM_DIR/scripts/deploy/deploy-agent-config.sh"

echo "Recreating hermes containers..."
docker compose -f "$PLATFORM_DIR/docker-compose.platform.yml" \
  "${COMPOSE_ENV_ARGS[@]}" \
  --project-name qacey-platform \
  up -d --no-build --no-deps --force-recreate hermes-justin hermes-annique

echo "Done. Hermes is restarting."
