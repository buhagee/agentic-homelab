#!/usr/bin/env bash
# Install the 10-minute deploy reconciliation timer.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${PLATFORM_DIR}/infrastructure/deploy"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root (sudo)" >&2
  exit 1
fi

if [[ ! -f /etc/sudoers.d/qacey-deploy ]]; then
  echo "ERROR: install the deploy dispatcher first (install-deploy-dispatcher.sh)" >&2
  exit 1
fi

for unit in qacey-deploy-reconcile.service qacey-deploy-reconcile.timer; do
  install -o root -g root -m 0644 "${UNIT_DIR}/${unit}" "/etc/systemd/system/${unit}"
  sed -i "s|__PLATFORM_DIR__|${PLATFORM_DIR}|g" "/etc/systemd/system/${unit}"
done

systemctl daemon-reload
systemctl enable --now qacey-deploy-reconcile.timer

echo "Installed qacey-deploy-reconcile.timer"
systemctl list-timers qacey-deploy-reconcile.timer --no-pager
