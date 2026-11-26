#!/usr/bin/env bash
# =============================================================================
# scripts/maintenance/install-backup.sh — Install backup systemd units + restic
# =============================================================================
# Installs:
# - restic (if not already installed)
# - qacey-db-backup.service (database dumps)
# - qacey-backup.service (local mirror + B2)
# - qacey-backup.timer (nightly at 16:00 UTC / 02:00 AEST)
# - qacey-backup-verify.service/timer (daily repository and age check)
#
# Run as: sudo bash scripts/maintenance/install-backup.sh
# =============================================================================
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_UNIT_DIR="${PLATFORM_DIR}/infrastructure/backup"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "ERROR: This script must be run as root (use sudo)"
   exit 1
fi

echo "=== Installing Qacey Platform Backup System ==="
echo ""

# ── Install restic ────────────────────────────────────────────────────────────
if ! command -v restic &> /dev/null; then
    echo "Installing restic..."
    apt-get update
    apt-get install -y restic
    echo "✓ restic installed: $(restic version)"
else
    echo "✓ restic already installed: $(restic version)"
fi
echo ""

# ── Install systemd units ─────────────────────────────────────────────────────
echo "Installing systemd units..."

for unit_name in \
    qacey-db-backup.service \
    qacey-backup.service \
    qacey-backup.timer \
    qacey-backup-verify.service \
    qacey-backup-verify.timer; do
    if [[ ! -f "${BACKUP_UNIT_DIR}/${unit_name}" ]]; then
        echo "ERROR: missing backup unit source: ${BACKUP_UNIT_DIR}/${unit_name}" >&2
        exit 1
    fi
done

# Database backup service
cp "${BACKUP_UNIT_DIR}/qacey-db-backup.service" /etc/systemd/system/
sed -i "s|__PLATFORM_DIR__|${PLATFORM_DIR}|g" /etc/systemd/system/qacey-db-backup.service
echo "✓ Installed qacey-db-backup.service"

# Main backup service
cp "${BACKUP_UNIT_DIR}/qacey-backup.service" /etc/systemd/system/
sed -i "s|__PLATFORM_DIR__|${PLATFORM_DIR}|g" /etc/systemd/system/qacey-backup.service
echo "✓ Installed qacey-backup.service"

# Backup timer
cp "${BACKUP_UNIT_DIR}/qacey-backup.timer" /etc/systemd/system/
echo "✓ Installed qacey-backup.timer"

# Offsite verification service and timer
cp "${BACKUP_UNIT_DIR}/qacey-backup-verify.service" /etc/systemd/system/
sed -i "s|__PLATFORM_DIR__|${PLATFORM_DIR}|g" /etc/systemd/system/qacey-backup-verify.service
echo "✓ Installed qacey-backup-verify.service"
cp "${BACKUP_UNIT_DIR}/qacey-backup-verify.timer" /etc/systemd/system/
echo "✓ Installed qacey-backup-verify.timer"

echo ""

# ── Reload systemd ────────────────────────────────────────────────────────────
echo "Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ systemd reloaded"
echo ""

# ── Enable and start timer ────────────────────────────────────────────────────
echo "Enabling backup timer..."
systemctl enable qacey-backup.timer
systemctl start qacey-backup.timer
echo "✓ Timer enabled and started"
echo ""

echo "Enabling offsite verification timer..."
systemctl enable qacey-backup-verify.timer
systemctl start qacey-backup-verify.timer
echo "✓ Verification timer enabled and started"
echo ""

# ── Status ────────────────────────────────────────────────────────────────────
echo "=== Backup System Status ==="
systemctl status qacey-backup.timer --no-pager || true
systemctl status qacey-backup-verify.timer --no-pager || true
echo ""
echo "Next scheduled runs:"
systemctl list-timers qacey-backup.timer qacey-backup-verify.timer --no-pager
echo ""

# ── Test instructions ─────────────────────────────────────────────────────────
echo "=== Installation Complete ==="
echo ""
echo "To test the backup system:"
echo "  1. Test database backup:  sudo bash ${PLATFORM_DIR}/scripts/maintenance/db-backup.sh"
echo "  2. Test full backup:      sudo bash ${PLATFORM_DIR}/scripts/maintenance/backup.sh --dry-run"
echo "  3. Run actual backup:     sudo systemctl start qacey-backup.service"
echo "  4. Check logs:            sudo journalctl -u qacey-backup.service -f"
echo "  5. Verify offsite:        sudo bash ${PLATFORM_DIR}/scripts/maintenance/backup.sh --verify-offsite"
echo "  6. Verify timer:          sudo systemctl start qacey-backup-verify.service"
echo "  7. Verify logs:           sudo journalctl -u qacey-backup-verify.service -f"
echo ""
echo "Backup logs are also written to:"
echo "  - /var/log/qacey-db-backup.log"
echo "  - /var/log/qacey-backup.log"
echo ""
