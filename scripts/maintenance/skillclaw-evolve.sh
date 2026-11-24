#!/usr/bin/env bash
# =============================================================================
# skillclaw-evolve.sh — trigger one SkillClaw skill-evolution cycle
# =============================================================================
# Runs nightly via host cron. The skillclaw evolve server's internal periodic
# loop is set to 24h (effectively idle); this script drives the actual run at a
# fixed time so it doesn't drift and doesn't clash with other CPU-heavy LLM jobs.
#
# The evolve server uses Google AI (fast, cloud). It drains
# captured agent sessions from the shared store, judges them, and evolves the
# shared skill library. Output is logged; nothing is delivered to chat.
# =============================================================================
set -euo pipefail

if ! docker inspect skillclaw >/dev/null 2>&1; then
  echo "$(date -u +%FT%TZ) skillclaw container not found — skipping" >&2
  exit 0
fi

# Step 1: import both agents' native Hermes sessions into the shared store.
# (Reads agents' own session logs — no proxy in the agents' request path.)
# Reset the import state first so all sessions are re-evaluated each run.
# The evolve server drains (deletes) sessions after processing, so without
# resetting state the importer would skip already-seen files and feed nothing
# to the evolve server on subsequent runs.
echo "$(date -u +%FT%TZ) importing Hermes sessions..."
docker exec -e SKILLCLAW_SHARED_ROOT=/skills/shared skillclaw \
  rm -f /skills/shared/.import-state.json
docker exec -e SKILLCLAW_SHARED_ROOT=/skills/shared skillclaw \
  python3 /opt/skillclaw/import-hermes-sessions.py \
  || { echo "$(date -u +%FT%TZ) session import failed" >&2; exit 1; }

# Step 2: trigger one evolve cycle (runs via Google AI — fast).
echo "$(date -u +%FT%TZ) triggering SkillClaw evolve cycle..."
docker exec skillclaw curl -sf -m 1800 -X POST http://localhost:8787/trigger \
  || { echo "$(date -u +%FT%TZ) trigger failed" >&2; exit 1; }
echo ""
echo "$(date -u +%FT%TZ) evolve cycle complete"
