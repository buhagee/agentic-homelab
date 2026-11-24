#!/usr/bin/env bash
# Shared environment contract for platform scripts.
# Source this file; it does not execute on its own.

load_platform_env() {
  local platform_dir="${1:?platform directory required}"
  local env_file

  for env_file in "${platform_dir}/.env" "${platform_dir}/secrets/.env"; do
    [[ -f "$env_file" ]] || continue

    # Accept only simple KEY=VALUE records and reject command substitutions.
    # Existing env files use shell-compatible quoting for values containing
    # spaces or special characters.
    if grep -Eq '^[A-Z_][A-Z0-9_]*=.*(`|\$\()' "$env_file"; then
      echo "Unsafe command substitution in environment file: $env_file" >&2
      return 1
    fi
    set -a
    # shellcheck disable=SC1090
    source <(grep -E '^[A-Z_][A-Z0-9_]*=' "$env_file" | grep -v '^#')
    set +a
  done
}

set_platform_compose_env_args() {
  local platform_dir="${1:?platform directory required}"

  COMPOSE_ENV_ARGS=(
    --env-file "${platform_dir}/versions.env"
    --env-file "${platform_dir}/.env"
  )
  if [[ -f "${platform_dir}/secrets/.env" ]]; then
    COMPOSE_ENV_ARGS+=(--env-file "${platform_dir}/secrets/.env")
  fi
}
