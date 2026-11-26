#!/usr/bin/env bash
# Verify every Compose image reference is tagged and resolvable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RETRY_DELAY="${CHECK_IMAGES_RETRY_DELAY:-2}"

cd "${REPO_ROOT}"

if [[ -n "${QACEY_IMAGES_OVERRIDE:-}" ]]; then
  if [[ ! -f "${QACEY_IMAGES_OVERRIDE}" ]]; then
    echo "ERROR: image override file not found: ${QACEY_IMAGES_OVERRIDE}" >&2
    exit 1
  fi
  mapfile -t images < "${QACEY_IMAGES_OVERRIDE}"
else
  if ! images_output="$(
    docker compose -f docker-compose.platform.yml \
      --profile '*' \
      --env-file versions.env \
      --env-file "${COMPOSE_ENV_FILE:-.env.ci}" \
      --project-name qacey-platform config --images
  )"; then
    echo "ERROR: docker compose config failed; cannot list images" >&2
    exit 1
  fi
  mapfile -t images <<< "${images_output}"
fi

declare -A seen=()
failed=0
checked=0

for image in "${images[@]}"; do
  image="${image//[[:space:]]/}"
  [[ -z "${image}" ]] && continue

  if [[ "${image}" == qacey/*:local ]]; then
    continue
  fi

  if [[ -n "${seen[${image}]:-}" ]]; then
    continue
  fi
  seen[${image}]=1
  checked=$((checked + 1))

  tag_part="${image%%@*}"
  if [[ "${tag_part}" == *:latest ]]; then
    echo "ERROR: latest tag is not allowed: ${image}" >&2
    failed=1
    continue
  fi

  if [[ "${image}" != *@sha256:* ]]; then
    final="${image##*/}"
    if [[ "${final}" == *: ]]; then
      echo "ERROR: empty image tag: ${image}" >&2
      failed=1
      continue
    fi
    if [[ "${final}" != *:* ]]; then
      echo "ERROR: untagged image reference: ${image}" >&2
      failed=1
      continue
    fi
  fi

  inspect_ref="${image}"
  if [[ "${image}" == *@sha256:* ]]; then
    name_tag="${image%@*}"
    digest="${image##*@}"
    final="${name_tag##*/}"
    if [[ "${final}" == *:* ]]; then
      name_tag="${name_tag%:*}"
    fi
    inspect_ref="${name_tag}@${digest}"
  fi

  resolved=0
  inspect_err=""
  for _attempt in 1 2 3; do
    if inspect_err="$(docker manifest inspect "${inspect_ref}" 2>&1 >/dev/null)"; then
      resolved=1
      break
    fi
    sleep "${RETRY_DELAY}"
  done

  if [[ "${resolved}" -ne 1 ]]; then
    echo "ERROR: unable to resolve image: ${image}" >&2
    if [[ -n "${inspect_err}" ]]; then
      printf '%s\n' "${inspect_err}" | tail -n 3 >&2
    fi
    failed=1
  fi
done

if [[ "${checked}" -eq 0 ]]; then
  echo "ERROR: no images were inspected" >&2
  exit 1
fi

exit "${failed}"
