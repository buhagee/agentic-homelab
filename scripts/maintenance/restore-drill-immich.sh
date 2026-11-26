#!/usr/bin/env bash
# Restore the newest Immich PostgreSQL dump into a throwaway container.
# Production Immich and its data are not touched.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/maintenance/restore-drill-lib.sh
source "${PLATFORM_DIR}/scripts/maintenance/restore-drill-lib.sh"
# shellcheck source=versions.env
set -a
source "${PLATFORM_DIR}/versions.env"
set +a

[[ "${EUID}" -eq 0 ]] || { echo "Run as root (sudo)" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }
[[ -n "${IMMICH_POSTGRES_VERSION:-}" ]] || { echo "IMMICH_POSTGRES_VERSION is missing" >&2; exit 1; }

DUMP="$(restore_drill_latest_dump immich)" || true
[[ -n "${DUMP}" ]] || { echo "No Immich dump found in /mnt/hdd1/qacey/db-backups" >&2; exit 1; }

echo "Immich restore drill"
echo "Dump: ${DUMP} ($(du -h "${DUMP}" | cut -f1))"
echo "Image: ghcr.io/immich-app/postgres:${IMMICH_POSTGRES_VERSION}"

legacy_usage="$(gunzip -c "${DUMP}" | grep -c 'vectors\.' || true)"
if (( legacy_usage > 0 )); then
  echo "ERROR: dump uses vectors.* types; a matching pgvecto.rs extension image is required" >&2
  exit 1
fi

DRILL_CONTAINER=""
trap restore_drill_cleanup EXIT

restore_drill_start_postgres \
  "ghcr.io/immich-app/postgres:${IMMICH_POSTGRES_VERSION}" \
  immich \
  immich

restore_drill_ensure_database immich immich

echo "Skipping legacy vectors extension (no vectors.* type usage found)."
gunzip -c "${DUMP}" \
  | grep -vE '^(CREATE EXTENSION IF NOT EXISTS vectors|COMMENT ON EXTENSION vectors|ALTER EXTENSION vectors)' \
  | docker exec -i "${DRILL_CONTAINER}" \
      psql -U immich -d immich -v ON_ERROR_STOP=1 >/dev/null

if count="$(restore_drill_query immich immich 'select count(*) from assets;' 2>/dev/null)"; then
  echo "Immich assets restored: ${count}"
else
  count="$(restore_drill_query immich immich \
    "select count(*) from information_schema.tables where table_schema='public';")"
  echo "Immich public tables restored: ${count}"
fi
[[ -n "${count}" ]] || { echo "Restored database did not answer a count query" >&2; exit 1; }

media_root="/mnt/hdd2/qacey/hdd1-mirror/immich"
sample=""
if [[ -d "${media_root}" ]]; then
  for subdir in upload library thumbs encoded-video; do
    [[ -d "${media_root}/${subdir}" ]] || continue
    sample="$(find "${media_root}/${subdir}" -type f ! -name '*.lock' -print -quit 2>/dev/null || true)"
    [[ -n "${sample}" ]] && break
  done
  if [[ -n "${sample}" ]]; then
    echo "Media mirror sample: ${sample}"
  else
    echo "WARN: media mirror exists but no upload/library/thumb sample was found" >&2
  fi
else
  echo "WARN: media mirror not found at ${media_root}" >&2
fi

echo "Immich restore drill passed. Production was not touched."
