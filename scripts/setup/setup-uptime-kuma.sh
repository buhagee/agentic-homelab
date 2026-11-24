#!/usr/bin/env bash
# scripts/setup-uptime-kuma.sh
# Programmatically configure Uptime Kuma: all service monitors.
#
# Prerequisites:
#   1. Uptime Kuma running (oracle-deploy.sh done)
#   2. Admin account created at https://platform-status.example.com
#   3. .env.oracle filled in: UPTIME_KUMA_USERNAME, UPTIME_KUMA_PASSWORD
#
# Run ON the Oracle VPS:
#   bash scripts/setup-uptime-kuma.sh
#
# Safe to re-run — skips monitors/notifications that already exist.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.oracle"

# ── Load .env.oracle ──────────────────────────────────────────────────────────
[[ -f "$ENV_FILE" ]] || { echo "[ERR] .env.oracle not found"; exit 1; }
set -a; source "$ENV_FILE"; set +a

# ── Validate required vars ────────────────────────────────────────────────────
for var in UPTIME_KUMA_USERNAME UPTIME_KUMA_PASSWORD; do
  [[ -n "${!var:-}" ]] || { echo "[ERR] $var is not set in .env.oracle"; exit 1; }
done

export UPTIME_KUMA_USERNAME="$UPTIME_KUMA_USERNAME"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Uptime Kuma Setup"
echo "═══════════════════════════════════════════════════"

# ── Install uptime-kuma-api Python library ────────────────────────────────────
echo "  [INFO] Installing uptime-kuma-api..."
PIP=$(which pip3 || which pip)
$PIP install --quiet --break-system-packages "uptime-kuma-api>=1.2.1" 2>/dev/null \
  || $PIP install --quiet "uptime-kuma-api>=1.2.1"

# ── Run Python config script ──────────────────────────────────────────────────
python3 - <<PYEOF
import os, sys

try:
    from uptime_kuma_api import UptimeKumaApi, MonitorType
except ImportError:
    print("[ERR] uptime-kuma-api not installed")
    sys.exit(1)

DOMAIN   = os.environ.get("QACEY_DOMAIN", "example.com")
URL      = "http://localhost:3001"
USERNAME = os.environ["UPTIME_KUMA_USERNAME"]
PASSWORD = os.environ["UPTIME_KUMA_PASSWORD"]

MONITORS = [
    {"name": "Immich (Photos)",    "url": f"https://photos.{DOMAIN}/api/server/ping"},
    {"name": "Vaultwarden (Vault)", "url": f"https://vault.{DOMAIN}"},
    {"name": "Paperless",           "url": f"https://paperless.{DOMAIN}"},
    {"name": "Hermes Sandbox",      "url": f"https://sandbox.{DOMAIN}"},
    {"name": "Scrutiny (Drive Health)", "url": f"https://drive-health.{DOMAIN}"},
    {"name": "AdGuard Home (DNS)", "url": f"https://adguard.{DOMAIN}"},
    {"name": "Home Assistant",      "url": f"https://ha.{DOMAIN}"},
]

print(f"  [INFO] Connecting to Uptime Kuma at {URL}...")
with UptimeKumaApi(URL) as api:
    api.login(USERNAME, PASSWORD)
    print(f"  [OK]   Logged in as {USERNAME}")

    # ── Monitors ──────────────────────────────────────────────────────────────
    existing_monitors = api.get_monitors()
    existing_monitor_names = {m["name"] for m in existing_monitors}

    for mon in MONITORS:
        if mon["name"] in existing_monitor_names:
            print(f"  [SKIP] Monitor already exists: {mon['name']}")
            continue
        print(f"  [INFO] Adding monitor: {mon['name']} → {mon['url']}")
        api.add_monitor(
            type=MonitorType.HTTP,
            name=mon["name"],
            url=mon["url"],
            interval=60,
            retryInterval=60,
            maxretries=3,
        )
        print(f"  [OK]   Added: {mon['name']}")

print("")
print("  [OK]   Setup complete — all monitors configured")
PYEOF

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Done. Check https://platform-status.example.com"
echo ""
echo "  Email notifications are configured manually:"
echo "    Settings → Notifications → Setup SMTP"
echo "    Host: smtp.gmail.com   Port: 587"
echo "    User: your Google Workspace sender address"
echo "    Password: the Google app password from .env.oracle"
echo "    From/To: ALERT_EMAIL_FROM / ALERT_EMAIL_TO"
echo "═══════════════════════════════════════════════════"
echo ""
