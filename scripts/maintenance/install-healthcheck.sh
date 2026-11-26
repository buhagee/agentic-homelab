#!/usr/bin/env bash
# Install the host-level Qacey container healthcheck systemd timer.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${PLATFORM_DIR}/infrastructure/health"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root (use sudo)" >&2
  exit 1
fi

for unit in qacey-healthcheck.service qacey-healthcheck.timer; do
  [[ -f "${UNIT_DIR}/${unit}" ]] || {
    echo "ERROR: missing unit ${UNIT_DIR}/${unit}" >&2
    exit 1
  }
  cp "${UNIT_DIR}/${unit}" /etc/systemd/system/
  sed -i "s|__PLATFORM_DIR__|${PLATFORM_DIR}|g" "/etc/systemd/system/${unit}"
done

systemctl daemon-reload
systemctl enable --now qacey-healthcheck.timer
systemctl status qacey-healthcheck.timer --no-pager || true
systemctl list-timers qacey-healthcheck.timer --no-pager
