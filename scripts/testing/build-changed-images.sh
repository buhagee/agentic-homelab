#!/usr/bin/env bash
# Build only the Compose services whose local build context contains a changed file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-.env.ci}"

cd "${REPO_ROOT}"

tmp_compose=""
cleanup() {
  if [[ -n "${tmp_compose}" ]]; then
    rm -f "${tmp_compose}"
  fi
  return 0
}
trap cleanup EXIT

if [[ -n "${QACEY_CHANGED_FILES:-}" ]]; then
  if [[ ! -f "${QACEY_CHANGED_FILES}" ]]; then
    echo "ERROR: changed-files override not found: ${QACEY_CHANGED_FILES}" >&2
    exit 1
  fi
  mapfile -t changed < "${QACEY_CHANGED_FILES}"
  compose_json="${QACEY_COMPOSE_JSON:?QACEY_COMPOSE_JSON is required with QACEY_CHANGED_FILES}"
else
  if [[ $# -ne 2 ]]; then
    echo "Usage: $0 BASE_SHA HEAD_SHA" >&2
    exit 2
  fi
  if ! changed_output="$(git diff --name-only "$1...$2")"; then
    echo "ERROR: git diff failed for $1...$2" >&2
    exit 1
  fi
  mapfile -t changed <<< "${changed_output}"
  tmp_compose="$(mktemp)"
  if ! docker compose -f docker-compose.platform.yml \
    --profile '*' \
    --env-file versions.env \
    --env-file "${COMPOSE_ENV_FILE}" \
    --project-name qacey-platform config --format json > "${tmp_compose}"; then
    echo "ERROR: docker compose config failed; cannot map build contexts" >&2
    exit 1
  fi
  compose_json="${tmp_compose}"
fi

if ! contexts_output="$(
  python3 - "${compose_json}" "${REPO_ROOT}" <<'PY'
import json
import os
import sys

compose_path, repo_root = sys.argv[1], sys.argv[2]
with open(compose_path, encoding="utf-8") as handle:
    data = json.load(handle)

for name, service in data.get("services", {}).items():
    build = service.get("build")
    if not build:
        continue
    context = build.get("context") if isinstance(build, dict) else build
    if not context:
        continue
    if context.startswith(("http://", "https://", "git@", "github.com/")):
        continue
    context = context.replace("${PLATFORM_DIR}", repo_root)
    if not os.path.isabs(context):
        context = os.path.join(repo_root, context)
    print(f"{name}\t{os.path.abspath(context)}")
PY
)"; then
  echo "ERROR: failed to parse Compose build contexts" >&2
  exit 1
fi
mapfile -t contexts <<< "${contexts_output}"

declare -A seen=()
services=()

for changed_file in "${changed[@]}"; do
  [[ -z "${changed_file}" ]] && continue
  if [[ "${changed_file}" == *__pycache__* || "${changed_file}" == *.pyc ]]; then
    continue
  fi
  absolute="${REPO_ROOT}/${changed_file}"
  while IFS=$'\t' read -r service context; do
    [[ -z "${service}" ]] && continue
    if [[ "${absolute}" == "${context}" || "${absolute}" == "${context}"/* ]]; then
      if [[ -z "${seen[${service}]:-}" ]]; then
        seen[${service}]=1
        services+=("${service}")
      fi
    fi
  done <<< "$(printf '%s\n' "${contexts[@]}")"
done

if [[ ${#services[@]} -eq 0 ]]; then
  echo "no local images changed"
  exit 0
fi

echo "building changed local images: ${services[*]}"
docker compose -f docker-compose.platform.yml \
  --profile '*' \
  --env-file versions.env \
  --env-file "${COMPOSE_ENV_FILE}" \
  --project-name qacey-platform build "${services[@]}"
