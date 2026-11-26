#!/usr/bin/env bash
# Deploy a merged main commit with a pre-deploy database dump and health gate.
# Dry run: bash scripts/deploy/auto-deploy.sh --dry-run <sha>
set -euo pipefail

PLATFORM_DIR="${QACEY_DEPLOY_PLATFORM_DIR:-$HOME/projects/qacey-platform}"
LOG_FILE="${QACEY_DEPLOY_LOG:-/var/log/qacey-deploy.log}"
STATE_DIR="${HOME}/.local/state/qacey-deploy"
LOCK_FILE="${QACEY_DEPLOY_LOCK:-/var/lock/qacey-deploy.lock}"
DB_BACKUP_DIR="/mnt/hdd1/qacey/db-backups"
DRY_RUN=0
SHA=""

usage() {
  echo "Usage: $0 [--dry-run] <40-character-sha>" >&2
  exit 2
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage ;;
    *) SHA="$arg" ;;
  esac
done

[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "ERROR: invalid 40-character SHA: $SHA" >&2; exit 2; }
[[ -d "$PLATFORM_DIR/.git" ]] || { echo "ERROR: not a git repository: $PLATFORM_DIR" >&2; exit 1; }

cd "$PLATFORM_DIR"
mkdir -p "$STATE_DIR"
FAILED_SHA_FILE="$STATE_DIR/failed-sha"
LAST_GOOD_FILE="$STATE_DIR/last-good"

if [[ "$DRY_RUN" -eq 0 ]]; then
  exec >> "$LOG_FILE" 2>&1
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "another deploy is running; skipping"
    exit 0
  fi
fi

RECOVERING=0
[[ -f "$FAILED_SHA_FILE" ]] && RECOVERING=1

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "ERROR: tracked changes in $PLATFORM_DIR; commit or stash them before deploying" >&2
  exit 1
fi

git fetch --quiet origin main

if ! git cat-file -e "${SHA}^{commit}" 2>/dev/null; then
  echo "ERROR: commit not found: $SHA" >&2
  exit 1
fi

if ! git merge-base --is-ancestor "$SHA" origin/main; then
  echo "ERROR: target $SHA is not on origin/main" >&2
  exit 1
fi

TIP="$(git rev-parse origin/main)"
if [[ "$SHA" != "$TIP" ]]; then
  echo "target $SHA superseded by ${TIP}; skipping"
  exit 0
fi

if git show-ref --verify --quiet refs/heads/main; then
  if ! git merge-base --is-ancestor main "$SHA"; then
    echo "ERROR: local main has commits that are not on origin/main; reconcile before deploying" >&2
    exit 1
  fi
fi

PREVIOUS="$(git rev-parse HEAD)"
if [[ -f "$LAST_GOOD_FILE" ]]; then
  PREVIOUS="$(cat "$LAST_GOOD_FILE")"
fi

CHANGED="$(git diff --name-only "$PREVIOUS" "$SHA")"
STATEFUL=0

if grep -qx 'docker-compose.platform.yml' <<< "$CHANGED"; then
  STATEFUL=1
fi
if grep -Eq '^services/agent/' <<< "$CHANGED"; then
  STATEFUL=1
fi

VERSION_DIFF=""
VERSION_BUILDS=()
if grep -qx 'versions.env' <<< "$CHANGED"; then
  VERSION_DIFF="$(git diff -U0 "$PREVIOUS" "$SHA" -- versions.env || true)"
  if grep -Eq '^[+-](IMMICH_VERSION|IMMICH_POSTGRES_VERSION|PAPERLESS_VERSION|POSTGRES_VERSION|REDIS_VERSION|HERMES_VERSION|HERMES_WEBUI_VERSION|MNEMO_PGVECTOR_VERSION|VAULTWARDEN_VERSION|HOMEASSISTANT_VERSION|CROWDSEC_VERSION|ADGUARD_VERSION|WIREGUARD_VERSION|OLLAMA_VERSION)=' <<< "$VERSION_DIFF"; then
    STATEFUL=1
  fi
  if grep -Eq '^[+-]HERMES_VERSION=' <<< "$VERSION_DIFF"; then
    VERSION_BUILDS+=("hermes-justin" "hermes-annique")
  fi
  if grep -Eq '^[+-](OPENCODE_V2_VERSION|OPENCODE_V2_NODE_VERSION|OPENCODE_V2_PNPM_VERSION)=' <<< "$VERSION_DIFF"; then
    VERSION_BUILDS+=("opencode-v2")
  fi
fi

if [[ "$RECOVERING" -eq 1 ]]; then
  STATEFUL=1
fi

ALREADY_DEPLOYED=0
if [[ -f "$LAST_GOOD_FILE" \
  && "$SHA" == "$(cat "$LAST_GOOD_FILE")" \
  && "$SHA" == "$(git rev-parse HEAD)" \
  && "$RECOVERING" -eq 0 ]]; then
  ALREADY_DEPLOYED=1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "target=$SHA"
  echo "previous=$PREVIOUS"
  echo "stateful=$STATEFUL"
  echo "already_deployed=$ALREADY_DEPLOYED"
  echo "version_builds=$(printf '%s ' "${VERSION_BUILDS[@]}" | sed 's/ $//')"
  echo "changed=$(tr '\n' ' ' <<< "$CHANGED" | sed 's/ $//')"
  exit 0
fi

if [[ -f "$FAILED_SHA_FILE" && "$(cat "$FAILED_SHA_FILE")" == "$SHA" ]]; then
  echo "$SHA previously failed; skipping until a fix-forward commit"
  exit 0
fi

# shellcheck source=scripts/lib/alert.sh
source scripts/lib/alert.sh

alert() {
  send_alert "$1" "$2" || true
}

die() {
  local message="$1"
  echo "ERROR: $message"
  alert "Qacey deploy failed" "$message"
  exit 1
}

compose() {
  local env_args=(--env-file versions.env --env-file .env)
  if [[ -f secrets/.env ]]; then
    env_args+=(--env-file secrets/.env)
  fi
  docker compose -f docker-compose.platform.yml \
    "${env_args[@]}" \
    --project-name qacey-platform "$@"
}

refresh_controller() {
  python3 scripts/setup/install-opencode-docker-control.py
}

refresh_native_development() {
  local helper=/usr/local/sbin/qacey-dev-deploy
  # A separate, explicit bootstrap installs this root-owned boundary. Never run
  # privileged native provisioning directly from this operator-owned checkout.
  if [[ ! -e "$helper" && ! -L "$helper" ]]; then
    return 0
  fi
  if [[ -x "$helper" ]] && sudo -n "$helper" apply "$SHA"; then
    return 0
  fi
  echo "ERROR: platform $SHA is healthy; native development update requires attention"
  alert "Qacey development update failed" \
    "Platform $SHA is healthy. Native updating failed; inspect qacey-dev-deploy status. The platform was not rolled back."
  return 1
}

# Containers whose services were removed from Compose. Keep this list so the
# next deploy does not leave an orphan running.
RETIRED_CONTAINERS=(skillclaw)

retire_containers() {
  local name
  for name in "${RETIRED_CONTAINERS[@]}"; do
    if docker inspect "$name" >/dev/null 2>&1; then
      echo "Removing retired container: $name"
      docker rm -f "$name" || return 1
    fi
  done
}

verify_fresh_dumps() {
  local prefix
  for prefix in immich paperless mnemo_justin mnemo_annique; do
    if ! find "$DB_BACKUP_DIR" -maxdepth 1 -type f \
      \( -name "${prefix}_*.sql.gz" -o -name "${prefix}_*.sqlite3.gz" \) \
      -newermt '-2 hours' -size +100c 2>/dev/null | grep -q .; then
      die "no database dump newer than 2 hours for $prefix"
    fi
  done
}

build_images() {
  COMPOSE_ENV_FILE=.env bash scripts/testing/build-changed-images.sh "$PREVIOUS" "$SHA" || return 1
  if [[ ${#VERSION_BUILDS[@]} -gt 0 ]]; then
    compose build "${VERSION_BUILDS[@]}" || return 1
  fi
}

deploy_stack() {
  # shellcheck source=scripts/lib/platform-env.sh
  source scripts/lib/platform-env.sh
  # shellcheck source=scripts/lib/render-config.sh
  source scripts/lib/render-config.sh
  load_platform_env "$PWD" || return 1
  render_traefik_dynamic "$PWD" || return 1
  # shellcheck source=scripts/lib/allowlist.sh
  source scripts/lib/allowlist.sh
  require_allowlist "$PWD" || return 1
  refresh_controller \
    && compose pull --ignore-buildable \
    && compose up -d --wait --wait-timeout 300 \
    && bash scripts/maintenance/platform-healthcheck.sh \
    && retire_containers
}

if [[ "$ALREADY_DEPLOYED" -eq 1 ]]; then
  git checkout --force -B main "$SHA"
  echo "=== Qacey deploy no-op: $SHA already deployed ==="
  refresh_controller
  retire_containers \
    && if bash scripts/maintenance/platform-healthcheck.sh; then
      printf '%s\n' "$SHA" > "$LAST_GOOD_FILE"
      if ! refresh_native_development; then exit 1; fi
      exit 0
    fi
  die "healthcheck failed for already-deployed SHA $SHA"
fi

echo ""
echo "=== Qacey deploy started: $(date '+%Y-%m-%dT%H:%M:%S%z') target=$SHA previous=$PREVIOUS stateful=$STATEFUL ==="

sudo -n systemctl start qacey-db-backup.service || die "database dump service failed"
verify_fresh_dumps

git checkout --force -B main "$SHA"

if ! build_images; then
  printf '%s\n' "$SHA" > "$FAILED_SHA_FILE"
  git checkout --force -B main "$PREVIOUS"
  die "changed-image build failed; restored $PREVIOUS"
fi

if deploy_stack; then
  printf '%s\n' "$SHA" > "$LAST_GOOD_FILE"
  rm -f "$FAILED_SHA_FILE"
  echo "=== Qacey deploy succeeded: $SHA ==="
  # Native state has its own transaction. A failed or deferred native update
  # must never enter the platform rollback path below.
  if ! refresh_native_development; then exit 1; fi
  exit 0
fi

if [[ "$STATEFUL" -eq 1 ]]; then
  printf '%s\n' "$SHA" > "$FAILED_SHA_FILE"
  alert "Qacey deploy failed (stateful)" \
    "Target $SHA from $PREVIOUS failed. Containers were left in place; restore manually from $DB_BACKUP_DIR if needed."
  exit 1
fi

alert "Qacey deploy failed; rolling back" \
  "Target $SHA from $PREVIOUS failed; rolling back to $PREVIOUS."

printf '%s\n' "$SHA" > "$FAILED_SHA_FILE"

git checkout --force -B main "$PREVIOUS"

if ! build_images; then
  die "rollback image build failed; inspect $PLATFORM_DIR"
fi

if deploy_stack; then
  echo "=== Rolled back to $PREVIOUS ==="
  exit 1
fi

die "rollback to $PREVIOUS also failed"
