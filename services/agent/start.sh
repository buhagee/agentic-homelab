#!/usr/bin/env bash
# Start both Hermes dashboard (9119) and gateway (8642).
# Dashboard runs in background; gateway is foreground/PID-1 process.
# Dashboard binds HERMES_DASHBOARD_HOST (default 127.0.0.1); the Traefik route
# sets it to 0.0.0.0 and supplies HERMES_DASHBOARD_USERNAME/_PASSWORD so a
# public bind is never unauthenticated. Gateway API binds only to the
# dedicated peer net regardless.
set -euo pipefail

# Prevent gateway locks, session files, and other runtime state from being
# created group/world-readable when the host volume is shared.
umask 077

# HOME must stay inside HERMES_HOME (/opt/data) so the dashboard file browser
# can read tool state and files emitted in chat.
export HOME="${HOME:-/opt/data/home}"
mkdir -p "$HOME"

# Compatibility bridge for old chat links that used ~/.hermes/skills.
if [[ ! -e "$HOME/skills" ]]; then
	ln -s /opt/data/skills "$HOME/skills"
fi

# Agent work must live under HERMES_HOME so the dashboard can preview it.
WORKSPACE="${HERMES_WORKSPACE_DIR:-/opt/data/workspace}"
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

LOCK_DIR="${HOME}/.local/state/hermes/gateway-locks"
if [[ -d "$LOCK_DIR" ]]; then
	find "$LOCK_DIR" -type d -exec chmod 700 {} +
	find "$LOCK_DIR" -type f -exec chmod 600 {} +
fi

HERMES=/opt/hermes/.venv/bin/hermes
DASHBOARD_HOST="${HERMES_DASHBOARD_HOST:-127.0.0.1}"

$HERMES dashboard --host "$DASHBOARD_HOST" --port 9119 --no-open &

exec $HERMES gateway run
