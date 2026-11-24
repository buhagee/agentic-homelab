#!/bin/bash
# =============================================================================
# immich-face-to-album.sh — Sync faces to albums using immich-face-to-album
# =============================================================================
# Reads mappings from immich-face-to-album.conf and runs a sync job for each.
# Each mapping declares which user's API key to use (JUSTIN or ANNIQUE), so
# the plugin only sees photos owned by that account.
#
# USAGE:
#   ./immich-face-to-album.sh [OPTIONS]
#
# OPTIONS:
#   -d, --dry-run       Print commands without executing them
#   -m, --mapping NAME  Run only the named mapping (e.g. --mapping JUSTIN)
#   -l, --list          List all configured mappings and exit
#   -h, --help          Show this help
#
# EXAMPLES:
#   ./immich-face-to-album.sh                    # run all mappings
#   ./immich-face-to-album.sh --mapping JUSTIN   # run one mapping
#   ./immich-face-to-album.sh --dry-run          # preview commands
#   ./immich-face-to-album.sh --list             # show configured mappings
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_FILE="${SCRIPT_DIR}/immich-face-to-album.conf"
ENV_FILE="${SCRIPT_DIR}/immich-face-to-album.env"
LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/face-to-album-$(date +%Y%m%d-%H%M%S).log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"

log() {
    local level="$1"; shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_info()    { log "INFO   " "${BLUE}$*${NC}"; }
log_success() { log "SUCCESS" "${GREEN}$*${NC}"; }
log_warning() { log "WARNING" "${YELLOW}$*${NC}"; }
log_error()   { log "ERROR  " "${RED}$*${NC}"; }
log_section() { log "------" "${CYAN}$*${NC}"; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
usage() {
    grep '^#' "$0" | grep -v '^#!/' | sed 's/^# \{0,1\}//'
}

check_plugin() {
    local plugin_dir="/opt/qacey/immich-plugins/face-to-album"
    local venv_python="${plugin_dir}/venv/bin/python"
    local main_script="${plugin_dir}/immich_face_to_album/__main__.py"

    if [[ ! -f "$venv_python" ]]; then
        log_error "Plugin venv not found at: $venv_python"
        log_error "Run: bash scripts/setup/setup-immich-plugins.sh"
        exit 1
    fi
    if [[ ! -f "$main_script" ]]; then
        log_error "Plugin script not found at: $main_script"
        exit 1
    fi

    # Return a callable: "python /path/to/__main__.py"
    echo "$venv_python $main_script"
}

# Resolve the API key for a given user token (JUSTIN, ANNIQUE, ...)
resolve_api_key() {
    local user="$1"
    local key_var="IMMICH_API_KEY_${user}"
    local key="${!key_var:-}"
    if [[ -z "$key" ]]; then
        log_error "No API key found for user '${user}' — expected ${key_var} in $ENV_FILE"
        return 1
    fi
    if [[ "$key" == *"<"* ]]; then
        log_warning "API key for '${user}' is still a placeholder — skipping"
        return 1
    fi
    echo "$key"
}

# Discover all mapping names from the conf file
discover_mappings() {
    grep -oP '^MAPPING_\K[A-Z0-9_]+(?=_FACES=)' "$CONF_FILE" | sort -u
}

# Validate a mapping has required fields and no placeholder IDs
validate_mapping() {
    local name="$1"
    local user_var="MAPPING_${name}_USER"
    local faces_var="MAPPING_${name}_FACES"
    local album_var="MAPPING_${name}_ALBUM"
    local user="${!user_var:-}"
    local faces="${!faces_var:-}"
    local album="${!album_var:-}"

    if [[ -z "$user" ]]; then
        log_warning "Mapping ${name}: no USER set — skipping"
        return 1
    fi
    if [[ -z "$faces" ]]; then
        log_warning "Mapping ${name}: no FACES set — skipping"
        return 1
    fi
    if [[ -z "$album" ]]; then
        log_warning "Mapping ${name}: no ALBUM set — skipping"
        return 1
    fi
    if [[ "$faces" == *"<"* ]] || [[ "$album" == *"<"* ]]; then
        log_warning "Mapping ${name}: contains placeholder IDs — skipping (fill in real UUIDs in conf)"
        return 1
    fi
    return 0
}

# Run a single mapping
run_mapping() {
    local name="$1"
    local plugin_bin="$2"
    local plugin_args="$3"
    local dry_run="$4"

    local user_var="MAPPING_${name}_USER"
    local faces_var="MAPPING_${name}_FACES"
    local album_var="MAPPING_${name}_ALBUM"
    local label_var="MAPPING_${name}_LABEL"
    local require_all_var="MAPPING_${name}_REQUIRE_ALL"

    local user="${!user_var}"
    local faces="${!faces_var}"
    local album="${!album_var}"
    local label="${!label_var:-$name}"
    local require_all="${!require_all_var:-false}"

    # Resolve API key for this user
    local api_key
    api_key=$(resolve_api_key "$user") || return 1

    log_section "Mapping: ${label}"
    log_info "  User   : ${user}"
    log_info "  Album  : ${album}"
    log_info "  Faces  : ${faces}"
    log_info "  AND    : ${require_all}"

    # Build command
    local cmd=("$plugin_bin" $plugin_args --key "$api_key" --server "$IMMICH_SERVER_URL" --album "$album")

    for face_id in $faces; do
        cmd+=(--face "$face_id")
    done

    if [[ "$require_all" == "true" ]]; then
        cmd+=(--require-all-faces)
    fi

    if [[ "$dry_run" == "true" ]]; then
        # Redact the key in dry-run output
        local display_cmd=("${cmd[@]/$api_key/<api-key>}")
        log_warning "  DRY RUN — would execute: ${display_cmd[*]}"
        return 0
    fi

    log_info "  Running sync..."
    if "${cmd[@]}" 2>&1 | tee -a "$LOG_FILE"; then
        log_success "  Mapping '${label}' completed"
    else
        log_error "  Mapping '${label}' failed — check log: $LOG_FILE"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    local dry_run=false
    local only_mapping=""
    local list_only=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -d|--dry-run)    dry_run=true; shift ;;
            -m|--mapping)    only_mapping="${2^^}"; shift 2 ;;
            -l|--list)       list_only=true; shift ;;
            -h|--help)       usage; exit 0 ;;
            *) log_error "Unknown option: $1"; usage; exit 1 ;;
        esac
    done

    # Load credentials
    if [[ ! -f "$ENV_FILE" ]]; then
        log_error "Env file not found: $ENV_FILE"
        log_error "Copy immich-face-to-album.env.example to immich-face-to-album.env and fill in values"
        exit 1
    fi
    source "$ENV_FILE"

    if [[ -z "${IMMICH_SERVER_URL:-}" ]]; then
        log_error "IMMICH_SERVER_URL not set in $ENV_FILE"
        exit 1
    fi

    # Load mapping config
    if [[ ! -f "$CONF_FILE" ]]; then
        log_error "Config file not found: $CONF_FILE"
        exit 1
    fi
    source "$CONF_FILE"

    # Discover mappings
    mapfile -t all_mappings < <(discover_mappings)

    if [[ ${#all_mappings[@]} -eq 0 ]]; then
        log_error "No mappings found in $CONF_FILE"
        exit 1
    fi

    # --list mode
    if [[ "$list_only" == "true" ]]; then
        echo ""
        echo "Configured mappings in $CONF_FILE:"
        echo ""
        for name in "${all_mappings[@]}"; do
            local user_var="MAPPING_${name}_USER"
            local label_var="MAPPING_${name}_LABEL"
            local faces_var="MAPPING_${name}_FACES"
            local album_var="MAPPING_${name}_ALBUM"
            local user="${!user_var:-<not set>}"
            local label="${!label_var:-$name}"
            local faces="${!faces_var:-<not set>}"
            local album="${!album_var:-<not set>}"
            local status="✓"
            if [[ "$faces" == *"<"* ]] || [[ "$album" == *"<"* ]]; then
                status="⚠ placeholder IDs"
            fi
            printf "  %-35s user=%-10s %s\n" "$name ($label)" "$user" "$status"
            printf "    faces : %s\n" "$faces"
            printf "    album : %s\n" "$album"
            echo ""
        done
        exit 0
    fi

    # Determine which mappings to run
    local mappings_to_run=()
    if [[ -n "$only_mapping" ]]; then
        mappings_to_run=("$only_mapping")
    else
        mappings_to_run=("${all_mappings[@]}")
    fi

    local plugin_bin
    local plugin_args
    read -r plugin_bin plugin_args <<< "$(check_plugin)"

    log_info "============================================"
    log_info "Immich Face-to-Album Sync"
    log_info "Server  : $IMMICH_SERVER_URL"
    log_info "Mappings: ${#mappings_to_run[@]}"
    log_info "Log     : $LOG_FILE"
    [[ "$dry_run" == "true" ]] && log_warning "Mode    : DRY RUN"
    log_info "============================================"
    echo ""

    local success=0
    local skipped=0
    local failed=0

    for name in "${mappings_to_run[@]}"; do
        if validate_mapping "$name"; then
            if run_mapping "$name" "$plugin_bin" "$plugin_args" "$dry_run"; then
                (( success++ )) || true
            else
                (( failed++ )) || true
            fi
        else
            (( skipped++ )) || true
        fi
        echo ""
    done

    log_info "============================================"
    log_info "Done — success: ${success}, skipped: ${skipped}, failed: ${failed}"
    log_info "============================================"

    [[ "$failed" -gt 0 ]] && exit 1
    return 0
}

trap 'log_error "Script interrupted"; exit 130' INT TERM

main "$@"
