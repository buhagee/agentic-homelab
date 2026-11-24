#!/usr/bin/env bash
# Install the daily Renovate trigger timer.
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${PLATFORM_DIR}/infrastructure/renovate"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root (sudo)" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh is not installed" >&2
  exit 1
fi

if ! runuser -u buhagiar -- gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated for buhagiar" >&2
  exit 1
fi

for unit in qacey-renovate.service qacey-renovate.timer; do
  install -o root -g root -m 0644 "${UNIT_DIR}/${unit}" "/etc/systemd/system/${unit}"
  sed -i "s|__PLATFORM_DIR__|${PLATFORM_DIR}|g" "/etc/systemd/system/${unit}"
done

systemctl daemon-reload
systemctl enable --now qacey-renovate.timer

echo "Installed qacey-renovate.timer"
systemctl list-timers qacey-renovate.timer --no-pager
