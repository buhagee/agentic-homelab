#!/usr/bin/env bash
# =============================================================================
# scripts/maintenance/backup.sh — Qacey Platform nightly backup
# =============================================================================
# Phase 1 (always): rsync local mirror SSD+HDD1 → HDD2
# Phase 2 (optional): restic → Backblaze B2 (only if all B2 vars present)
#
# Run as root via systemd timer (qacey-backup.timer) at 16:00 UTC
# (02:00 AEST / 03:00 AEDT).
# Manual run: sudo bash scripts/maintenance/backup.sh
# Dry run:    sudo bash scripts/maintenance/backup.sh --dry-run
# Verify B2:  sudo bash scripts/maintenance/backup.sh --verify-offsite
#
# On failure: email alert via scripts/lib/alert.sh
# On success: silent
# =============================================================================
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# shellcheck source=scripts/lib/platform-env.sh
source "${PLATFORM_DIR}/scripts/lib/platform-env.sh"
# shellcheck source=scripts/lib/alert.sh
source "${PLATFORM_DIR}/scripts/lib/alert.sh"

LOG_FILE="/var/log/qacey-backup.log"
MAX_DUMP_AGE_HOURS=2
REPO_SOFT_LIMIT_BYTES=$((8 * 1024 * 1024 * 1024))
REPO_TOTAL_LIMIT_BYTES=$((9 * 1024 * 1024 * 1024))
DRY_RUN=0
VERIFY_OFFSITE=0
ALERT_ON_ERROR=1
ALERT_SENT=0
RESTIC_REPO_WOULD_INIT=0

parse_args() {
  for arg in "$@"; do
    case "$arg" in
      --dry-run)
        DRY_RUN=1
        ;;
      --verify-offsite)
        VERIFY_OFFSITE=1
        ALERT_ON_ERROR=0
        ;;
      *)
        echo "Usage: $0 [--dry-run] [--verify-offsite]"
        return 1
        ;;
    esac
  done
}

fail() {
  local subject="$1"
  local body="$2"
  echo "ERROR: ${subject} — ${body}" >&2
  if [[ ${ALERT_ON_ERROR:-1} -eq 1 ]]; then
    send_alert "$subject" "$body" || true
  fi
  ALERT_SENT=1
  return 1
}

configure_restic_env() {
  local key
  local missing=()

  load_platform_env "$PLATFORM_DIR"

  for key in B2_ACCOUNT_ID B2_ACCOUNT_KEY B2_BUCKET RESTIC_PASSWORD; do
    [[ -n "${!key:-}" ]] || missing+=("$key")
  done

  if [[ ${#missing[@]} -eq 4 ]]; then
    return 2
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing offsite settings: ${missing[*]}" >&2
    return 1
  fi

  export B2_ACCOUNT_ID="$B2_ACCOUNT_ID"
  export B2_ACCOUNT_KEY="$B2_ACCOUNT_KEY"
  export RESTIC_REPOSITORY="b2:${B2_BUCKET}:/qacey"
  export RESTIC_PASSWORD="$RESTIC_PASSWORD"
  return 0
}

restic_repo_requires_init() {
  local rc="$1"
  local output="$2"

  [[ "$rc" -eq 10 ]] || return 1
  grep -qiE 'repository does not exist|unable to open config file|config file .* does not exist|Is there a repository at the following location' <<<"$output"
}

ensure_restic_repository_ready() {
  local output
  local rc

  RESTIC_REPO_WOULD_INIT=0

  set +e
  output="$(restic cat config 2>&1)"
  rc=$?
  set -e

  if [[ $rc -eq 0 ]]; then
    echo "Restic repository is accessible at $RESTIC_REPOSITORY."
    return 0
  fi

  if restic_repo_requires_init "$rc" "$output"; then
    echo "$output"

    if [[ $VERIFY_OFFSITE -eq 1 ]]; then
      echo "ERROR: restic repository is not initialised at $RESTIC_REPOSITORY."
      return 1
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
      RESTIC_REPO_WOULD_INIT=1
      echo "Dry run: repository would be initialised at $RESTIC_REPOSITORY before backup."
      return 0
    fi

    echo "Initialising restic repository at $RESTIC_REPOSITORY..."
    restic init
    return 0
  fi

  echo "ERROR: restic repository check failed before backup."
  echo "$output"
  return 1
}

append_latest_db_backups() {
  local backup_dir="/mnt/hdd1/qacey/db-backups"
  local prefix
  local latest_path
  local stale=()
  local max_age_minutes=$((MAX_DUMP_AGE_HOURS * 60))
  local prefixes=(immich paperless mnemo_justin mnemo_annique)

  for prefix in "${prefixes[@]}"; do
    latest_path="$({ find "$backup_dir" -maxdepth 1 -type f \
      \( -name "${prefix}_*.sql.gz" -o -name "${prefix}_*.sqlite3.gz" \) \
      -size +100c -mmin "-${max_age_minutes}" -printf '%T@ %p\n' 2>/dev/null || true; } \
      | sort -nr | head -n 1 | cut -d' ' -f2-)"

    if [[ -n "$latest_path" ]]; then
      RESTIC_PATHS+=("$latest_path")
    else
      stale+=("$prefix")
      echo "Warning: no database dump newer than ${MAX_DUMP_AGE_HOURS}h for ${prefix} in $backup_dir"
    fi
  done

  if [[ ${#stale[@]} -gt 0 ]]; then
    send_alert \
      "Qacey backup: stale database dumps" \
      "No dump newer than ${MAX_DUMP_AGE_HOURS}h for: ${stale[*]}. Offsite payload omits those dumps." \
      || true
  fi
}

verify_offsite_repository() {
  local restic_rc

  set +e
  configure_restic_env
  restic_rc=$?
  set -e

  if [[ $restic_rc -eq 2 ]]; then
    echo "ERROR: B2 credentials not set — cannot verify offsite backup."
    exit 1
  fi
  if [[ $restic_rc -ne 0 ]]; then
    echo "ERROR: B2 configuration is incomplete — cannot verify offsite backup."
    exit 1
  fi

  ensure_restic_repository_ready

  echo "Recent restic snapshots:"
  restic snapshots --compact --latest 5

  echo "Repository raw-data size:"
  restic stats --mode raw-data

  echo "Running sampled repository integrity check (1/50 data subset)..."
  restic check --read-data-subset=1/50
}

main() {
  parse_args "$@"

  # ── Logging ─────────────────────────────────────────────────────────────────
  exec >> "$LOG_FILE" 2>&1
  echo ""
  echo "=== Qacey backup started: $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
  [[ $DRY_RUN -eq 1 ]] && echo "[DRY RUN MODE]"
  [[ $VERIFY_OFFSITE -eq 1 ]] && echo "[OFFSITE VERIFICATION MODE]"

  # Trap unexpected errors
  trap 'if [[ ${ALERT_SENT:-0} -eq 0 && ${ALERT_ON_ERROR:-1} -eq 1 ]]; then send_alert "Qacey backup failed" "Unexpected error at line $LINENO. Check /var/log/qacey-backup.log." || true; fi; exit 1' ERR

  if [[ $VERIFY_OFFSITE -eq 1 ]]; then
    echo "--- Offsite verification ---"
    verify_offsite_repository
    echo "=== Qacey offsite verification finished: $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
    return 0
  fi

  # ── Pre-flight checks ───────────────────────────────────────────────────────
  for mp in /mnt/ssd /mnt/hdd1 /mnt/hdd2; do
    if ! mountpoint -q "$mp"; then
      echo "ERROR: $mp is not mounted — aborting backup."
      fail "Qacey backup failed" "$mp is not mounted. Backup aborted."
    fi
  done

  # ── Phase 1: Local mirror (always runs) ─────────────────────────────────────
  echo "--- Phase 1: Local mirror ---"

  RSYNC_OPTS="-aAX --delete --stats"
  [[ $DRY_RUN -eq 1 ]] && RSYNC_OPTS="$RSYNC_OPTS --dry-run"

  echo "Mirroring SSD → HDD2..."
  set +e
  rsync $RSYNC_OPTS /mnt/ssd/qacey/ /mnt/hdd2/qacey/ssd-mirror/
  rc=$?
  set -e
  if [[ $rc -ne 0 && $rc -ne 24 ]]; then
    fail "Qacey backup failed" "SSD → HDD2 rsync failed with exit code $rc. Check $LOG_FILE."
  elif [[ $rc -eq 24 ]]; then
    echo "SSD → HDD2 rsync completed with exit code 24 (some files vanished during transfer — warning only)."
  fi

  echo "Mirroring HDD1 → HDD2..."
  set +e
  rsync $RSYNC_OPTS /mnt/hdd1/qacey/ /mnt/hdd2/qacey/hdd1-mirror/
  rc=$?
  set -e
  if [[ $rc -ne 0 && $rc -ne 24 ]]; then
    fail "Qacey backup failed" "HDD1 → HDD2 rsync failed with exit code $rc. Check $LOG_FILE."
  elif [[ $rc -eq 24 ]]; then
    echo "HDD1 → HDD2 rsync completed with exit code 24 (some files vanished during transfer — warning only)."
  fi

  echo "Phase 1 complete."

  # ── Phase 2: Backblaze B2 via restic (optional) ─────────────────────────────
  local restic_rc
  set +e
  configure_restic_env
  restic_rc=$?
  set -e

  if [[ $restic_rc -eq 2 ]]; then
    echo "Phase 2: B2 credentials not set — skipping offsite backup."
  elif [[ $restic_rc -ne 0 ]]; then
    fail "Qacey backup configuration incomplete" "B2 settings are incomplete. See $LOG_FILE."
  else
    echo "--- Phase 2: Backblaze B2 via restic ---"

    RESTIC_PATHS=()
    DEPLOY_USER="${QACEY_DEPLOY_USER:-buhagiar}"
    DEPLOY_HOME="$(getent passwd "$DEPLOY_USER" 2>/dev/null | cut -d: -f6 || true)"
    AGENT_SECRETS_DIR="${AGENT_SECRETS_DIR:-${DEPLOY_HOME:-$HOME}/.config/qacey-secrets}"

    add_restic_path() {
      if [[ -e "$1" ]]; then
        RESTIC_PATHS+=("$1")
      fi
      return 0
    }

    # Deliberately small offsite set: stay under the Backblaze 10 GB free cap.
    # Raw PostgreSQL files are excluded in favour of logical dumps.
    add_restic_path /mnt/ssd/qacey/vaultwarden
    add_restic_path /mnt/ssd/qacey/paperless
    add_restic_path /mnt/ssd/qacey/traefik/certs
    add_restic_path /mnt/ssd/qacey/crowdsec
    add_restic_path /mnt/ssd/qacey/adguard/conf
    add_restic_path /mnt/ssd/qacey/wireguard
    add_restic_path /mnt/ssd/qacey/homeassistant
    add_restic_path /mnt/ssd/qacey/hermes/skills
    add_restic_path /mnt/ssd/qacey/hermes/users
    add_restic_path /mnt/ssd/qacey/hermes/wife
    add_restic_path /mnt/ssd/qacey/hermes/annique
    # Keep Justin's config/memory/profile state, not the multi-gigabyte session
    # and sandbox history.
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/config.yaml
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/.env
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/SOUL.md
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/memories
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/profiles
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/kanban.db
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/response_store.db
    add_restic_path /mnt/ssd/qacey/hermes/justin/data/google-workspace

    # Platform configuration and secrets. Restic encrypts the repository, so
    # these are protected at rest; keep RESTIC_PASSWORD outside the host.
    add_restic_path "${PLATFORM_DIR}/.env"
    add_restic_path "${PLATFORM_DIR}/secrets/.env"
    add_restic_path "${AGENT_SECRETS_DIR}"
    add_restic_path "${PLATFORM_DIR}/secrets/browser-oauth-allowed-emails.txt"
    add_restic_path "${PLATFORM_DIR}/docker-compose.platform.yml"
    add_restic_path "${PLATFORM_DIR}/versions.env"

    append_latest_db_backups

    payload_bytes=0
    for path in "${RESTIC_PATHS[@]}"; do
      size="$(du -sb "$path" 2>/dev/null | cut -f1 || true)"
      [[ "$size" =~ ^[0-9]+$ ]] || size=0
      payload_bytes=$((payload_bytes + size))
    done
    if (( payload_bytes > REPO_SOFT_LIMIT_BYTES )); then
      fail "Qacey backup cap guard" "offsite payload is ${payload_bytes} bytes, above the 8 GiB soft limit. Reduce the payload before backing up."
    fi
    echo "Offsite payload size: ${payload_bytes} bytes."

    echo "Offsite payload includes selected service state plus the newest database dump per service."
    printf ' - %s\n' "${RESTIC_PATHS[@]}"

    ensure_restic_repository_ready || {
      fail "Qacey backup failed" "restic repository check failed before backup. Check $LOG_FILE."
    }

    if command -v jq >/dev/null 2>&1; then
      if repo_json="$(restic --no-lock stats --mode raw-data --json 2>/dev/null)"; then
        repo_size="$(jq -r '.total_size // 0' <<<"$repo_json")"
        if [[ "$repo_size" =~ ^[0-9]+$ ]] && (( repo_size > REPO_SOFT_LIMIT_BYTES )); then
          fail "Qacey backup cap guard" "restic repository is ${repo_size} bytes, above the 8 GiB soft limit. Prune or raise the B2 cap before backing up."
        fi
        if [[ "$repo_size" =~ ^[0-9]+$ ]] && (( repo_size + payload_bytes > REPO_TOTAL_LIMIT_BYTES )); then
          fail "Qacey backup cap guard" "repo plus payload is $((repo_size + payload_bytes)) bytes, above the 9 GiB total limit."
        fi
      else
        echo "Warning: could not read restic repository size; skipping the cap guard."
      fi
    else
      echo "Warning: jq not found; skipping the restic repo-size guard."
    fi

    if [[ $RESTIC_REPO_WOULD_INIT -eq 1 ]]; then
      echo "Phase 2 dry run skipped because the restic repository is not initialised yet."
    else
      BACKUP_CMD=(restic backup --exclude-caches)

      # Exclude heavy Paperless originals from offsite backup to limit B2 usage.
      # Operators may choose to manage originals in a separate bucket or paid tier.
      if [[ -d "/mnt/ssd/qacey/paperless/media/originals" ]]; then
        echo "Excluding /mnt/ssd/qacey/paperless/media/originals from offsite backup."
        BACKUP_CMD+=(--exclude "/mnt/ssd/qacey/paperless/media/originals")
      fi

      [[ $DRY_RUN -eq 1 ]] && BACKUP_CMD+=(--dry-run)
      BACKUP_CMD+=("${RESTIC_PATHS[@]}")

      "${BACKUP_CMD[@]}" || {
        fail "Qacey backup failed" "restic B2 backup failed. Check $LOG_FILE."
      }

      # Keep a short offsite history so the repository stays practical for the B2 free tier.
      if [[ $DRY_RUN -eq 0 ]]; then
        restic forget --prune --keep-last 2 || {
          fail "Qacey backup failed" "restic retention prune failed after backup. Check $LOG_FILE."
        }
      fi
    fi

    echo "Phase 2 complete."
  fi

  echo "=== Qacey backup finished: $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
