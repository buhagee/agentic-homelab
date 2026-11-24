#!/usr/bin/env bash
set -euo pipefail

workspace_root=${HOME}/projects

case "$PWD" in
  "$workspace_root")
    container_dir=/workspace
    ;;
  "$workspace_root"/*)
    container_dir="/workspace/${PWD#"$workspace_root"/}"
    ;;
  *)
    printf 'OpenCode must be started from a directory under %s\n' "$workspace_root" >&2
    exit 1
    ;;
esac

if ! docker inspect --format '{{.State.Running}}' opencode-v2 2>/dev/null | grep -qx true; then
  echo "OpenCode container 'opencode-v2' is not running." >&2
  exit 1
fi

if [[ -t 0 && -t 1 ]]; then
  exec docker exec -it -w "$container_dir" opencode-v2 \
    opencode --server http://127.0.0.1:4096 "$@"
else
  exec docker exec -w "$container_dir" opencode-v2 \
    opencode --server http://127.0.0.1:4096 "$@"
fi
