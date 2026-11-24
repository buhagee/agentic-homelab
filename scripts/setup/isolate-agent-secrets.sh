#!/usr/bin/env bash
# Move the platform secret files outside /srv and replace
# them with symlinks. The opencode-v2 container mounts only /srv,
# so the symlink targets are not readable inside the agent.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_DIR="${HOME}/.config/qacey-secrets"
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

[[ "$(id -un)" == "buhagiar" ]] || {
  echo "Run as the buhagiar host user, not root." >&2
  exit 1
}

move_secret() {
  local source="$1"
  local target="$2"

  if [[ -L "$source" ]]; then
    [[ -f "$target" ]] || {
      echo "ERROR: $source is a symlink but $target is missing" >&2
      exit 1
    }
    echo "Already isolated: $source -> $target"
    return 0
  fi

  [[ -f "$source" ]] || {
    echo "ERROR: missing secret file: $source" >&2
    exit 1
  }
  [[ ! -e "$target" ]] || {
    echo "ERROR: target already exists: $target" >&2
    exit 1
  }

  echo "Move: $source -> $target"
  if [[ $DRY_RUN -eq 1 ]]; then
    return 0
  fi

  install -d -m 0700 "$SECRETS_DIR"
  install -m 0600 "$source" "$target"
  if [[ "$(sha256sum "$source" | cut -d' ' -f1)" != "$(sha256sum "$target" | cut -d' ' -f1)" ]]; then
    echo "ERROR: checksum mismatch after copying $source" >&2
    exit 1
  fi
  rm -- "$source"
  ln -s "$target" "$source"
}

if [[ $DRY_RUN -eq 0 ]]; then
  install -d -m 0700 "$SECRETS_DIR"
fi
move_secret "${PLATFORM_DIR}/.env" "${SECRETS_DIR}/.env"
move_secret "${PLATFORM_DIR}/secrets/.env" "${SECRETS_DIR}/secrets.env"

cat <<EOF

Secret files are now under ${SECRETS_DIR}.
The opencode-v2 container does not mount that path.

Verify from the host:
  ls -l ${PLATFORM_DIR}/.env ${PLATFORM_DIR}/secrets/.env

Verify the agent cannot read them:
  docker exec opencode-v2 sh -c 'test ! -r /workspace/qacey-platform/.env'
  docker exec opencode-v2 sh -c 'test ! -r /workspace/qacey-platform/secrets/.env'

The next backup includes ${SECRETS_DIR}.
EOF
