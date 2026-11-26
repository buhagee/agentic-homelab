#!/bin/bash
# =============================================================================
# install-crontab.sh — Install cron jobs from crontab.txt
# =============================================================================
# Installs all scheduled jobs defined in scripts/crontab.txt into the current
# user's crontab. Safe to re-run — existing jobs from crontab.txt are replaced,
# any manually added jobs outside crontab.txt are preserved.
#
# USAGE:
#   bash scripts/install-crontab.sh
#   bash scripts/install-crontab.sh --dry-run   # preview without installing
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRONTAB_FILE="${SCRIPT_DIR}/crontab.txt"
LOG_DIR="/var/log/qacey-cron"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

if [[ ! -f "$CRONTAB_FILE" ]]; then
    error "crontab.txt not found at: $CRONTAB_FILE"
fi

# Extract the job lines from crontab.txt (skip comments and blanks)
mapfile -t new_jobs < <(grep -v '^\s*#' "$CRONTAB_FILE" | grep -v '^\s*$')

if [[ ${#new_jobs[@]} -eq 0 ]]; then
    warn "No jobs found in $CRONTAB_FILE"
    exit 0
fi

info "Jobs defined in crontab.txt:"
for job in "${new_jobs[@]}"; do
    echo "  $job"
done
echo ""

if [[ "$dry_run" == "true" ]]; then
    warn "DRY RUN — no changes made"
    exit 0
fi

# Create log directory
if [[ ! -d "$LOG_DIR" ]]; then
    sudo mkdir -p "$LOG_DIR"
    sudo chown "$(whoami)" "$LOG_DIR"
    success "Created log directory: $LOG_DIR"
fi

# Get current crontab, strip everything from the managed marker onwards,
# then also strip any lines whose command matches a job in crontab.txt
current_crontab=$(crontab -l 2>/dev/null || true)

# Remove everything from the managed marker line onwards (handles re-runs cleanly)
current_crontab=$(echo "$current_crontab" | sed '/^# ── Managed by scripts\/crontab.txt/,$d')

# Also strip any remaining lines whose command portion matches a managed job
filtered=""
while IFS= read -r line; do
    keep=true
    for job in "${new_jobs[@]}"; do
        job_cmd=$(echo "$job" | awk '{for(i=6;i<=NF;i++) printf "%s%s",$i,(i<NF?" ":"\n")}')
        if [[ "$line" == *"$job_cmd"* ]]; then
            keep=false
            break
        fi
    done
    [[ "$keep" == "true" ]] && filtered+="${line}"$'\n'
done <<< "$current_crontab"

# Build final crontab: preserved manual jobs + managed jobs from file
{
    # Existing non-managed jobs (strip trailing blank lines)
    echo "$filtered" | sed '/^[[:space:]]*$/d'
    echo ""
    echo "# ── Managed by scripts/crontab.txt — do not edit below this line ──"
    cat "$CRONTAB_FILE"
} | crontab -

success "Crontab installed. Current crontab:"
echo ""
crontab -l
