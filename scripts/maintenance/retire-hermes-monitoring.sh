#!/usr/bin/env bash
# Remove the retired Hermes server-monitoring cron jobs. Idempotent.
set -euo pipefail

if ! docker inspect hermes-justin >/dev/null 2>&1; then
  echo "hermes-justin is not present; nothing to retire." >&2
  exit 1
fi

for job in platform-monitor nightly-digest; do
  if docker exec hermes-justin hermes cron list 2>/dev/null | grep -q "$job"; then
    echo "Deleting Hermes cron job: $job"
    docker exec hermes-justin hermes cron delete "$job"
  else
    echo "Hermes cron job not found: $job"
  fi
done

docker exec hermes-justin hermes cron list || true
