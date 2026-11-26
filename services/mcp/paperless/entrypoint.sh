#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PAPERLESS_BASE_URL:-}" || -z "${PAPERLESS_API_TOKEN:-}" ]]; then
  echo "PAPERLESS_BASE_URL and PAPERLESS_API_TOKEN must be set in the environment"
  echo "Example: PAPERLESS_BASE_URL=http://paperless:8000 PAPERLESS_API_TOKEN=xxxxx"
  # keep container alive for debugging
  exec sleep infinity
fi

exec paperless-mcp "$PAPERLESS_BASE_URL" "$PAPERLESS_API_TOKEN" --http --port 8000 --host 0.0.0.0
