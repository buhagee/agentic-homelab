#!/usr/bin/env bash
# =============================================================================
# deploy-agent-config.sh — Deploy Hermes Agent config to host volumes
# =============================================================================
# Merges services/agent/config.shared.yaml + live Hermes UI state into the
# final config.yaml for each instance (HERMES_HOME=/opt/data).
# Git owns the base config. The UI owns mcp_servers, plugins, skills, and
# OAuth tokens. This script merges those live blocks back in.
# services/agent/mcp-servers*.json are migration references only, never applied.
# Variables in config.shared.yaml (e.g. ${HERMES_MODEL}) are substituted from
# .env plus the private secrets/.env overlay at deploy time.
#
# Usage:
#   bash scripts/deploy-agent-config.sh
#
# Note: Skills are managed via WebUI, not deployed by this script.
# =============================================================================
set -euo pipefail

# Config, runtime env, session databases, and gateway state contain private
# data. Keep newly-created files owner-only unless a later step opts in.
umask 077

# ── Parse flags ─────────────────────────────────────────────────────────────
# (No flags needed - skills managed via WebUI)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="${PLATFORM_DIR:-$(dirname "$(dirname "$SCRIPT_DIR")")}"
HERMES_SRC="${HERMES_SRC:-$PLATFORM_DIR/services/agent}"
HERMES_BASE_DIR="${HERMES_BASE_DIR:-/mnt/ssd/qacey/hermes}"
HERMES_STATE_MERGE="${HERMES_STATE_MERGE:-$PLATFORM_DIR/scripts/lib/hermes_state_merge.py}"

# data dirs (HERMES_HOME=/opt/data in base image — config.yaml lives here)
JUSTIN_DATA="${JUSTIN_DATA:-$HERMES_BASE_DIR/justin/data}"
ANNIQUE_DATA="${ANNIQUE_DATA:-$HERMES_BASE_DIR/annique/data}"

# hermes home dirs (for ~/.hermes runtime files)
JUSTIN_HOME="${JUSTIN_HOME:-$HERMES_BASE_DIR/justin/home}"
ANNIQUE_HOME="${ANNIQUE_HOME:-$HERMES_BASE_DIR/annique/home}"

GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${BLUE}[hermes-config]${NC} $*"; }
success() { echo -e "${GREEN}[hermes-config]${NC} $*"; }
warn()    { echo -e "${RED}[hermes-config WARN]${NC} $*" >&2; }
die()     { echo -e "${RED}[hermes-config ERROR]${NC} $*" >&2; exit 1; }

run_privileged() {
  if [[ $EUID -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

is_real_secret_value() {
  local value="${1:-}"

  [[ -n "$value" ]] && [[ ! "$value" =~ ^__.*__$ ]]
}

write_google_workspace_auth_file() {
  local dest_dir="$1"
  local refresh_token="$2"
  local user_label="$3"
  local auth_dir auth_file

  auth_dir="$dest_dir/google-workspace"
  auth_file="$auth_dir/auth.json"
  mkdir -p "$auth_dir"

  if ! is_real_secret_value "${GOOGLE_WORKSPACE_CLIENT_ID:-}" || ! is_real_secret_value "${GOOGLE_WORKSPACE_CLIENT_SECRET:-}"; then
    rm -f "$auth_file"
    info "${user_label}: Google Workspace shared OAuth client is not configured; skipping auth file"
    return
  fi

  if ! is_real_secret_value "$refresh_token"; then
    rm -f "$auth_file"
    info "${user_label}: Google Workspace refresh token is not configured; leaving auth file absent"
    return
  fi

  cat > "$auth_file" <<EOF
{
  "type": "authorized_user",
  "client_id": "${GOOGLE_WORKSPACE_CLIENT_ID}",
  "client_secret": "${GOOGLE_WORKSPACE_CLIENT_SECRET}",
  "refresh_token": "${refresh_token}",
  "token_uri": "https://oauth2.googleapis.com/token"
}
EOF
  chmod 600 "$auth_file"
  success "${user_label}: Google Workspace auth file written"
}

harden_private_tree() {
  local root="$1"

  [[ -d "$root" ]] || return 0
  run_privileged find "$root" -type d -exec chmod 700 {} +
  run_privileged find "$root" -type f -perm /111 -exec chmod 700 {} +
  run_privileged find "$root" -type f ! -perm /111 -exec chmod 600 {} +
}

harden_script_tree() {
  local root="$1"

  [[ -d "$root" ]] || return 0
  run_privileged find "$root" -type d -exec chmod 750 {} +
  run_privileged find "$root" -type f ! -perm /111 -exec chmod 640 {} +
  run_privileged find "$root" -type f -perm /111 -exec chmod 750 {} +
}

harden_runtime_permissions() {
  local data_dir home_dir path

  for data_dir in "$JUSTIN_DATA" "$ANNIQUE_DATA"; do
    for path in \
      config.yaml config.yaml.pre-deploy .env .env.pre-deploy SOUL.md state.db kanban.db response_store.db \
      verification_evidence.db auth.json mcp-servers.json \
      gateway_state.json channel_directory.json; do
      [[ -f "$data_dir/$path" ]] && chmod 600 "$data_dir/$path"
    done

    for path in sessions memories cron/output profiles mcp-tokens; do
      harden_private_tree "$data_dir/$path"
    done

    for path in scripts; do
      harden_script_tree "$data_dir/$path"
    done

  done

  for home_dir in "$JUSTIN_HOME" "$ANNIQUE_HOME"; do
    if [[ -d "$home_dir/.local/state/hermes/gateway-locks" ]]; then
      find "$home_dir/.local/state/hermes/gateway-locks" -type d -exec chmod 700 {} +
      find "$home_dir/.local/state/hermes/gateway-locks" -type f -exec chmod 600 {} +
    fi
    harden_script_tree "$home_dir/scripts"
  done
}

# ── Validate source files ────────────────────────────────────────────────────
for f in \
  "$HERMES_SRC/config.shared.yaml" \
  "$HERMES_SRC/persona.justin.md" \
  "$HERMES_SRC/persona.annique.md"; do
  [[ -f "$f" ]] || die "Missing source file: $f"
done

command -v python3 >/dev/null 2>&1 || die "python3 is required for Hermes config merge"
[[ -f "$HERMES_STATE_MERGE" ]] || die "Missing merge helper: $HERMES_STATE_MERGE"

# ── Load env files for variable substitution ────────────────────────────────
ENV_FILE="$PLATFORM_DIR/.env"
[[ -f "$ENV_FILE" ]] || die "Missing .env file: $ENV_FILE"
# shellcheck disable=SC1091
source "$PLATFORM_DIR/scripts/lib/platform-env.sh"
load_platform_env "$PLATFORM_DIR" || die "Could not load platform environment"

# ── Ensure directories exist ─────────────────────────────────────────────────
info "Ensuring directories..."
# The base hermes dir should exist from docker-compose volume mounts.
# Subdirs are owned by the hermes user.
if [[ ! -d "$HERMES_BASE_DIR" ]]; then
  die "$HERMES_BASE_DIR does not exist. Ensure docker-compose has created the volume mounts."
fi
mkdir -p "$JUSTIN_DATA" "$ANNIQUE_DATA" "$JUSTIN_HOME" "$ANNIQUE_HOME"
# U-07: Skill volume host directories (idempotent)
SKILLS_DIR="$HERMES_BASE_DIR/skills"
mkdir -p "$SKILLS_DIR/shared" "$SKILLS_DIR/justin" "$SKILLS_DIR/annique"
mkdir -p "$JUSTIN_DATA/workbooks" "$ANNIQUE_DATA/workbooks"
success "Directories ready"

# ── Resolve Hermes UID/GID ───────────────────────────────────────────────────
# Respect explicit values loaded from .env. The runtime files are owner-only,
# so the compose process UID must match the owner that writes them.
HERMES_UID="${HERMES_UID:-$(id -u hermes 2>/dev/null || echo 999)}"
HERMES_GID="${HERMES_GID:-$(id -g hermes 2>/dev/null || echo 982)}"

# ── Helper: render Git-owned base config and preserve UI-owned blocks ───────
# Usage: write_config_yaml <dest>
write_config_yaml() {
  local dest="$1"
  local overlay="$HERMES_SRC/config.${instance:-shared}.yaml"
  local tmp_yaml
  tmp_yaml="$(mktemp)"

  HERMES_TERMINAL_BACKEND="local"
  HERMES_TERMINAL_IMAGE=""
  export HERMES_TERMINAL_BACKEND HERMES_TERMINAL_IMAGE
  envsubst < "$HERMES_SRC/config.shared.yaml" > "$tmp_yaml"

  if [[ -f "$overlay" && "$overlay" != "$HERMES_SRC/config.shared.yaml" ]]; then
    envsubst < "$overlay" >> "$tmp_yaml"
  fi

  # Validate only the Git-owned base. UI-owned MCP entries may reference
  # variables that live only in the runtime .env and are not deploy inputs.
  warn_unresolved_runtime_references "$tmp_yaml"

  if [[ -f "$dest" ]]; then
    cp -p "$dest" "${dest}.pre-deploy"
    chmod 600 "${dest}.pre-deploy"
  fi

  python3 "$HERMES_STATE_MERGE" config \
    --base "$tmp_yaml" \
    --live "$dest" \
    --output "$dest"
  chmod 600 "$dest"

  rm -f "$tmp_yaml"
}

assert_no_embedded_secrets() {
  local config_file="$1" name value

  for name in \
    HA_LONG_LIVED_TOKEN \
    OPENCODE_GO_API_KEY OPENROUTER_API_KEY; do
    value="${!name:-}"
    if is_real_secret_value "$value" && grep -Fq -- "$value" "$config_file"; then
      die "Refusing to deploy embedded secret value in $config_file"
    fi
  done
}

warn_unresolved_runtime_references() {
  local config_file="$1" reference var
  local missing=()

  while IFS= read -r reference; do
    [[ -n "$reference" ]] || continue
    var="${reference:2:${#reference}-3}"
    if [[ -z "${!var+x}" || -z "${!var}" ]]; then
      missing+=("$var")
    fi
  done < <(grep -oE '\$\{[A-Z_][A-Z0-9_]*\}' "$config_file" | sort -u || true)

  if [[ ${#missing[@]} -gt 0 ]]; then
    warn "Unresolved runtime vars in $config_file: ${missing[*]}"
    if [[ "${STRICT_HERMES_CONFIG:-0}" == "1" ]]; then
      die "STRICT_HERMES_CONFIG=1 and runtime vars are missing"
    fi
  fi
}

# ── Generate and deploy config.yaml ─────────────────────────────────────────
info "Generating config.yaml for Justin..."
instance=justin write_config_yaml "$JUSTIN_DATA/config.yaml"
assert_no_embedded_secrets "$JUSTIN_DATA/config.yaml"
success "Justin: config.yaml written (UI-owned blocks preserved)"

info "Generating config.yaml for Annique..."
instance=annique write_config_yaml "$ANNIQUE_DATA/config.yaml"
assert_no_embedded_secrets "$ANNIQUE_DATA/config.yaml"
success "Annique: config.yaml written (UI-owned blocks preserved)"

# ── Deploy persona files (SOUL.md) ───────────────────────────────────────────
info "Deploying SOUL.md..."
cp "$HERMES_SRC/persona.justin.md" "$JUSTIN_DATA/SOUL.md"
chmod 600 "$JUSTIN_DATA/SOUL.md"
success "Justin: SOUL.md deployed"
cp "$HERMES_SRC/persona.annique.md" "$ANNIQUE_DATA/SOUL.md"
chmod 600 "$ANNIQUE_DATA/SOUL.md"
success "Annique: SOUL.md deployed"

# ── Deploy provider API keys to runtime .env files ───────────────────────────
# Each Hermes runtime reads HERMES_HOME/.env for provider keys (separate from
# the rendered config.yaml). Keep OpenRouter mirrored into OPENAI_API_KEY so
# auxiliary vision calls continue to use the OpenAI-compatible backend even when
# the main text provider switches to opencode-go.
#
# The merge updates only these repo-managed keys. UI-added MCP/plugin keys and
# comments are preserved.
write_runtime_env() {
  local dest="$1"

  OPENAI_API_KEY="${OPENROUTER_API_KEY:-}"
  export OPENAI_API_KEY

  if [[ -f "$dest" ]]; then
    cp -p "$dest" "${dest}.pre-deploy"
    chmod 600 "${dest}.pre-deploy"
  fi

  python3 "$HERMES_STATE_MERGE" env \
    --existing "$dest" \
    --output "$dest" \
    --managed-key OPENCODE_GO_API_KEY \
    --managed-key OPENCODE_GO_BASE_URL \
    --managed-key OPENROUTER_API_KEY \
    --managed-key OPENAI_API_KEY \
    --managed-key HERMES_IMAGE_GEN_MODEL \
    --managed-key SKILLCLAW_MODEL \
    --managed-key HA_LONG_LIVED_TOKEN
  chmod 600 "$dest"
}

info "Writing provider keys to runtime .env files..."
write_runtime_env "$JUSTIN_DATA/.env"
success "Justin: runtime .env merged (provider keys; UI keys preserved)"
write_runtime_env "$ANNIQUE_DATA/.env"
success "Annique: runtime .env merged (provider keys; UI keys preserved)"

info "Writing Google Workspace auth material..."
write_google_workspace_auth_file "$JUSTIN_DATA" "${GOOGLE_WORKSPACE_REFRESH_TOKEN_JUSTIN:-}" "Justin"
write_google_workspace_auth_file "$ANNIQUE_DATA" "${GOOGLE_WORKSPACE_REFRESH_TOKEN_ANNIQUE:-}" "Annique"

warn_google_workspace_mcp_without_auth() {
  local data_dir="$1" label="$2"

  [[ -f "$data_dir/google-workspace/auth.json" ]] && return 0
  if grep -q '^  google_workspace:' "$data_dir/config.yaml" 2>/dev/null; then
    warn "$label: google_workspace MCP is configured but auth material is absent."
    warn "$label: disable or remove google_workspace in the Hermes UI."
  fi
}

warn_google_workspace_mcp_without_auth "$JUSTIN_DATA" "Justin"
warn_google_workspace_mcp_without_auth "$ANNIQUE_DATA" "Annique"

harden_runtime_permissions

if [[ "${SKIP_AGENT_POST_DEPLOY_STEPS:-0}" == "1" ]]; then
  info "Skipping post-deploy runtime steps (SKIP_AGENT_POST_DEPLOY_STEPS=1)"
  exit 0
fi

# Skills and plugins are managed via the Hermes UI, not deployed by this script.

# ── U-06: Initialise mnemo-hermes databases ───────────────────────────────────
# Idempotent — safe to re-run. Only runs when mnemo-postgres container is up.
# Each agent gets its own database; pgvector extension enables vector search.
# ─────────────────────────────────────────────────────────────────────────────
MNEMO_POSTGRES_PASSWORD="${MNEMO_POSTGRES_PASSWORD:-}"
if [[ -z "$MNEMO_POSTGRES_PASSWORD" ]]; then
  echo "[WARN] MNEMO_POSTGRES_PASSWORD not set in .env — skipping DB init" >&2
elif docker inspect mnemo-postgres >/dev/null 2>&1; then
  info "Initialising mnemo databases..."
  for DBNAME in mnemo_justin mnemo_annique; do
    docker exec mnemo-postgres psql -U mnemo -d postgres -c \
      "CREATE DATABASE ${DBNAME};" 2>/dev/null || true
    docker exec mnemo-postgres psql -U mnemo -d "${DBNAME}" -c \
      "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true
  done
  success "mnemo databases ready (mnemo_justin, mnemo_annique)"
else
  echo "[WARN] mnemo-postgres not running — skipping DB init (re-run after first deploy)" >&2
fi

# ── Hermes plugins ───────────────────────────────────────────────────────────
# Do not pip-install plugins into /opt/hermes/.venv. That venv is sealed against
# the image's uv.lock, and runtime installs make Hermes report "install out of
# sync". Install plugins through `hermes plugins install` if one is needed later.

# ── U-16: Skills managed via WebUI ───────────────────────────────────────────
# Skills are now created and managed through the Hermes WebUI.
# No repo-based skill seeding. Users create skills from scratch via UI.

SKILLS_DIR="$HERMES_BASE_DIR/skills"

# Ensure skill directories exist with correct ownership
info "Ensuring skill directories exist..."
sudo mkdir -p "$SKILLS_DIR/shared" "$SKILLS_DIR/justin" "$SKILLS_DIR/annique"
sudo chown -R "${HERMES_UID}:${HERMES_GID}" "$SKILLS_DIR"
sudo find "$SKILLS_DIR" -type d -exec chmod 750 {} +
sudo find "$SKILLS_DIR" -type f ! -perm /111 -exec chmod 640 {} +
sudo find "$SKILLS_DIR" -type f -perm /111 -exec chmod 750 {} +
success "Skill directories ready (manage via WebUI)"

# ── U-09: Deploy Justin-only scripts ─────────────────────────────────────────
# Scripts live at ~/.hermes/scripts/ (HERMES_HOME/.hermes/scripts/) inside the container.
# Keep scripts group-readable/executable for the Hermes runtime, never world-readable.
JUSTIN_SCRIPTS_DIR="$JUSTIN_DATA/scripts"
if [[ -d "$HERMES_SRC/scripts" ]]; then
  info "Deploying Justin scripts..."
  sudo mkdir -p "$JUSTIN_SCRIPTS_DIR"
  sudo rsync -a "$HERMES_SRC/scripts/" "$JUSTIN_SCRIPTS_DIR/"
  sudo chown -R "${HERMES_UID}:${HERMES_GID}" "$JUSTIN_SCRIPTS_DIR"
  sudo find "$JUSTIN_SCRIPTS_DIR" -type d -exec chmod 750 {} +
  sudo find "$JUSTIN_SCRIPTS_DIR" -type f ! -perm /111 -exec chmod 640 {} +
  sudo find "$JUSTIN_SCRIPTS_DIR" -type f -perm /111 -exec chmod 750 {} +
  success "Justin scripts deployed to $JUSTIN_SCRIPTS_DIR"
fi
if [[ -d "$JUSTIN_SCRIPTS_DIR" ]]; then
  run_privileged rm -f "$JUSTIN_SCRIPTS_DIR/platform-monitor.sh" "$JUSTIN_SCRIPTS_DIR/nightly-digest.sh"
fi

# Deployed skill copies do not need upstream Git metadata. Removing nested
# repositories avoids leaking history and credentials accidentally committed
# upstream, while preserving all skill content.
if [[ "${PRUNE_SKILL_GIT_METADATA:-1}" == "1" ]]; then
  sudo find "$SKILLS_DIR" -type d -name .git -prune -exec rm -rf -- {} +
  info "Removed nested skill Git metadata"
fi

echo ""
info "Done. Restart containers to pick up the new config:"
info "  bash scripts/start.sh"
info "Or to reload MCP without restart, ask Hermes: /reload-mcp"

