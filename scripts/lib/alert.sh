#!/usr/bin/env bash
# Shared email alert wrapper. Source this file; it defines send_alert().
# The SMTP password is loaded from the platform env files and never printed.

ALERT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="${PLATFORM_DIR:-$(cd "${ALERT_LIB_DIR}/../.." && pwd)}"

# shellcheck source=scripts/lib/platform-env.sh
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"

send_alert() {
  local subject="${1:?alert subject required}"
  local body="${2:-$subject}"

  if ! load_platform_env "$PLATFORM_DIR"; then
    echo "alert: could not load platform environment for: $subject" >&2
    return 1
  fi

  if python3 "${PLATFORM_DIR}/scripts/lib/send_email.py" \
    --subject "$subject" --body "$body"; then
    return 0
  fi

  echo "alert: email delivery failed for: $subject" >&2
  return 1
}
