#!/usr/bin/env bash
# =============================================================================
# harden-hermes-data.sh — Restrict Hermes profile/script data on host volumes
# =============================================================================
# Safe operation: fix permissions only. No data is deleted.
# =============================================================================
set -euo pipefail
umask 077

HERMES_BASE_DIR="${HERMES_BASE_DIR:-/mnt/ssd/qacey/hermes}"
info() { printf '[hermes-data] %s\n' "$*"; }
die()  { printf '[hermes-data ERROR] %s\n' "$*" >&2; exit 1; }

run_privileged() {
  if [[ $EUID -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

usage() {
  cat <<'USAGE'
Usage:
  harden-hermes-data.sh [--base-dir DIR]

Default action restricts profile trees to owner-only and managed script trees
to owner/group access. It never deletes data.

--base-dir DIR        Override the Hermes host data root.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-dir)
      [[ $# -ge 2 ]] || die "--base-dir requires a directory"
      HERMES_BASE_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -d "$HERMES_BASE_DIR" ]] || die "Hermes base directory not found: $HERMES_BASE_DIR"

harden_private_tree() {
  local root="$1"

  [[ -d "$root" ]] || return 0
  run_privileged find "$root" -type d -exec chmod 700 {} +
  run_privileged find "$root" -type f -perm /111 -exec chmod 700 {} +
  run_privileged find "$root" -type f ! -perm /111 -exec chmod 600 {} +
}

harden_script_tree() {
  local root="$1"

  [[ -d "$root" ]] || return 0
  run_privileged find "$root" -type d -exec chmod 750 {} +
  run_privileged find "$root" -type f ! -perm /111 -exec chmod 640 {} +
  run_privileged find "$root" -type f -perm /111 -exec chmod 750 {} +
}

mapfile -t PROFILE_ROOTS < <(
  find "$HERMES_BASE_DIR" -type d -path '*/data/profiles' -print 2>/dev/null
)
mapfile -t SCRIPT_ROOTS < <(
  find "$HERMES_BASE_DIR" -type d \( \
    -path '*/data/scripts' -o -path '*/home/scripts' \
  \) -print 2>/dev/null
)

for root in "${PROFILE_ROOTS[@]}"; do
  harden_private_tree "$root"
done

for root in "${SCRIPT_ROOTS[@]}"; do
  harden_script_tree "$root"
done

if [[ ${#PROFILE_ROOTS[@]} -eq 0 && ${#SCRIPT_ROOTS[@]} -eq 0 ]]; then
  info "No Hermes profile/script roots found under $HERMES_BASE_DIR"
else
  info "Hermes profile/script permissions hardened"
fi