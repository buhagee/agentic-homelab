#!/usr/bin/env bash
# Shared preflight for the OAuth allowlist. Source this file; it does not execute.

require_allowlist() {
  local platform_dir="${1:?platform directory required}"
  local file="${platform_dir}/secrets/browser-oauth-allowed-emails.txt"

  if [[ ! -f "$file" ]]; then
    echo "ERROR: missing ${file}. Copy infrastructure/browser-oauth-allowed-emails.txt.example and add the approved addresses." >&2
    return 1
  fi
  if [[ ! -r "$file" ]]; then
    echo "ERROR: ${file} is not readable by this user" >&2
    return 1
  fi
  if ! grep -Eq '^[^#[:space:]]+@[^[:space:]]+$' "$file"; then
    echo "ERROR: ${file} contains no usable email addresses" >&2
    return 1
  fi
}
