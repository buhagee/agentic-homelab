#!/usr/bin/env bash
# =============================================================================
# proxy-entrypoint.sh — SkillClaw client proxy (session capture)
# =============================================================================
# Writes ~/.skillclaw/config.yaml non-interactively, then starts the proxy.
#
# Role: sits between both Hermes agents and OpenRouter. Forwards requests
# upstream unchanged (so interactive speed/quality is identical) while
# recording session artifacts to the shared local store. The skillclaw
# (evolve-server) service reads that store and evolves skills.
#
# Env (from docker-compose):
#   SKILLCLAW_UPSTREAM_BASE   OpenRouter base URL
#   SKILLCLAW_UPSTREAM_KEY    OpenRouter API key
#   SKILLCLAW_UPSTREAM_MODEL  model id the agents use (forwarded upstream)
#   SKILLCLAW_PROXY_PORT      port the proxy listens on (default 8788)
#   SKILLCLAW_SHARED_ROOT     shared local store path (mounted volume)
#   SKILLCLAW_GROUP_ID        sharing group id (qacey)
# =============================================================================
set -euo pipefail

CONFIG_DIR="${HOME}/.skillclaw"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
mkdir -p "${CONFIG_DIR}"

PROXY_PORT="${SKILLCLAW_PROXY_PORT:-8788}"
SHARED_ROOT="${SKILLCLAW_SHARED_ROOT:-/shared}"
GROUP_ID="${SKILLCLAW_GROUP_ID:-qacey}"

cat > "${CONFIG_FILE}" <<YAML
llm:
  provider: openai
  model_id: "${SKILLCLAW_UPSTREAM_MODEL}"
  api_base: "${SKILLCLAW_UPSTREAM_BASE}"
  api_key: "${SKILLCLAW_UPSTREAM_KEY}"
proxy:
  port: ${PROXY_PORT}
  host: 0.0.0.0
  api_key: ""
  served_model_name: skillclaw-model
# This container is not a CLI agent host — do not rewrite any agent config.
claw_type: none
configure_openclaw: false
# PRM scoring defaults to OpenAI (gpt-5.x) — we have no OpenAI key, so disable it.
prm:
  enabled: false
record_enabled: true
record_dir: "${SHARED_ROOT}/records"
skills:
  enabled: false
# Write captured sessions to the shared local store the evolve-server reads.
sharing:
  enabled: true
  backend: local
  local_root: "${SHARED_ROOT}"
  group_id: "${GROUP_ID}"
  user_alias: proxy
  auto_pull_on_start: false
  # CRITICAL: sessions are only uploaded to {group_id}/sessions/ when this is > 0.
  # Left at the default of 0, the evolve-server never sees any sessions and the
  # whole capture->evolve loop silently does nothing. 1 = upload after each user turn.
  session_upload_interval: 1
YAML

echo "[skillclaw-proxy] wrote ${CONFIG_FILE}:"
sed 's/\(api_key: "\).*\(".*\)/\1***\2/' "${CONFIG_FILE}"

echo "[skillclaw-proxy] starting proxy on :${PROXY_PORT} (upstream: ${SKILLCLAW_UPSTREAM_BASE})"
# Run in foreground (not --daemon) so the container stays alive and logs stream.
exec skillclaw start --port "${PROXY_PORT}"
