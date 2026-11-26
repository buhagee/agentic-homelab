#!/usr/bin/env bash
# Install the allowlisted dispatcher and its sudoers rules.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SOURCE="${SCRIPT_DIR}/homeserver-deploy"
TARGET="/usr/local/sbin/homeserver-deploy"
SUDOERS="/etc/sudoers.d/qacey-deploy"
LOG_FILE="/var/log/qacey-deploy.log"
LOCK_FILE="/var/lock/qacey-deploy.lock"

id github-runner >/dev/null 2>&1 || {
  echo "Create the github-runner user first with install-github-runner.sh" >&2
  exit 1
}
id buhagiar >/dev/null 2>&1 || {
  echo "Missing host user: buhagiar" >&2
  exit 1
}

SYSTEMCTL="$(command -v systemctl)"
[[ -n "$SYSTEMCTL" ]] || {
  echo "systemctl not found" >&2
  exit 1
}

install -o root -g root -m 0755 "$SOURCE" "$TARGET"
sed -i "s|__PLATFORM_DIR__|${PLATFORM_DIR}|g" "$TARGET"

cat > "$SUDOERS" <<EOF
github-runner ALL=(root) NOPASSWD: ${TARGET}
buhagiar ALL=(root) NOPASSWD: ${SYSTEMCTL} start qacey-db-backup.service
EOF
chmod 0440 "$SUDOERS"
visudo -cf "$SUDOERS"

touch "$LOG_FILE" "$LOCK_FILE"
chown buhagiar:buhagiar "$LOG_FILE" "$LOCK_FILE"
chmod 0640 "$LOG_FILE"
chmod 0600 "$LOCK_FILE"

echo "Installed ${TARGET}"
echo "Installed ${SUDOERS}"
echo "Prepared ${LOG_FILE} and ${LOCK_FILE}"
