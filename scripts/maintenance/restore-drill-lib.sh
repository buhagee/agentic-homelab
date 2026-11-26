#!/usr/bin/env bash
# Shared helpers for non-destructive PostgreSQL restore drills.
# The caller must set a trap to restore_drill_cleanup.

set -euo pipefail

restore_drill_cleanup() {
  if [[ -n "${DRILL_CONTAINER:-}" ]]; then
    docker rm -f "${DRILL_CONTAINER}" >/dev/null 2>&1 || true
  fi
}

restore_drill_latest_dump() {
  local prefix="$1"
  local directory="${2:-/mnt/hdd1/qacey/db-backups}"
  find "${directory}" -maxdepth 1 -type f -name "${prefix}_*.sql.gz" -size +100c \
    -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | head -n 1 \
    | cut -d' ' -f2-
}

restore_drill_free_port() {
  python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

restore_drill_start_postgres() {
  local image="$1"
  local user="$2"
  local database="$3"

  DRILL_PORT="$(restore_drill_free_port)"
  DRILL_CONTAINER="qacey-restore-drill-${user}-$$"

  docker run -d --rm \
    --name "${DRILL_CONTAINER}" \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    -e "POSTGRES_USER=${user}" \
    -e "POSTGRES_DB=${database}" \
    -p "127.0.0.1:${DRILL_PORT}:5432" \
    "${image}" >/dev/null

  local attempt
  for attempt in {1..60}; do
    if docker exec "${DRILL_CONTAINER}" pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "ERROR: drill Postgres did not become ready" >&2
  return 1
}

restore_drill_ensure_database() {
  local user="$1"
  local database="$2"
  local attempt

  if docker exec "${DRILL_CONTAINER}" \
      psql -U "${user}" -d "${database}" -c 'select 1' >/dev/null 2>&1; then
    return 0
  fi

  # The entrypoint may still be creating the database. Ignore a duplicate
  # createdb race and wait for the database to accept connections.
  docker exec "${DRILL_CONTAINER}" createdb -U "${user}" "${database}" \
    >/dev/null 2>&1 || true

  for attempt in {1..60}; do
    if docker exec "${DRILL_CONTAINER}" \
        psql -U "${user}" -d "${database}" -c 'select 1' >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "ERROR: drill database ${database} did not become ready" >&2
  return 1
}

restore_drill_restore_dump() {
  local dump="$1"
  local user="$2"
  local database="$3"

  gzip -t "${dump}"
  gunzip -c "${dump}" \
    | docker exec -i "${DRILL_CONTAINER}" \
        psql -U "${user}" -d "${database}" -v ON_ERROR_STOP=1 >/dev/null
}

restore_drill_query() {
  local user="$1"
  local database="$2"
  local sql="$3"

  docker exec "${DRILL_CONTAINER}" \
    psql -U "${user}" -d "${database}" -Atc "${sql}"
}
