#!/bin/bash
#
# Simple Immich Bulk Upload Script
# Uploads from a single folder (recursively) - no complex logic
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/immich-bulk-upload.env"
LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/simple-upload-$(date +%Y%m%d-%H%M%S).log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Load environment
if [[ ! -f "$ENV_FILE" ]]; then
    echo -e "${RED}Error: Environment file not found: $ENV_FILE${NC}"
    exit 1
fi

source "$ENV_FILE"

# Validate required variables
required_vars=("IMMICH_SERVER_URL" "IMMICH_API_KEY" "SOURCE_DEVICE" "SOURCE_MOUNT_PATH")
for var in "${required_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo -e "${RED}Error: Required variable $var is not set in $ENV_FILE${NC}"
        exit 1
    fi
done

mkdir -p "$LOG_DIR"

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_info() { log "INFO" "${BLUE}$*${NC}"; }
log_success() { log "SUCCESS" "${GREEN}$*${NC}"; }
log_warning() { log "WARNING" "${YELLOW}$*${NC}"; }
log_error() { log "ERROR" "${RED}$*${NC}"; }

check_immich_go() {
    if ! command -v immich-go &> /dev/null; then
        log_error "immich-go is not installed"
        exit 1
    fi
    log_info "Found immich-go: $(immich-go version 2>&1 || echo 'unknown')"
}

is_mounted() {
    mountpoint -q "$SOURCE_MOUNT_PATH" 2>/dev/null
}

mount_drive() {
    if is_mounted; then
        log_info "Drive already mounted at $SOURCE_MOUNT_PATH"
        return 0
    fi
    
    log_info "Mounting $SOURCE_DEVICE to $SOURCE_MOUNT_PATH..."
    
    if [[ ! -d "$SOURCE_MOUNT_PATH" ]]; then
        sudo mkdir -p "$SOURCE_MOUNT_PATH"
    fi
    
    if sudo mount "$SOURCE_DEVICE" "$SOURCE_MOUNT_PATH"; then
        log_success "Drive mounted successfully"
        return 0
    else
        log_error "Failed to mount drive"
        return 1
    fi
}

unmount_drive() {
    if ! is_mounted; then
        log_info "Drive not mounted"
        return 0
    fi
    
    log_info "Unmounting $SOURCE_MOUNT_PATH..."
    
    if sudo umount "$SOURCE_MOUNT_PATH"; then
        log_success "Drive unmounted successfully"
        return 0
    else
        log_error "Failed to unmount drive"
        return 1
    fi
}

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Simple bulk upload script - uploads from a single folder recursively.

OPTIONS:
    -s, --source PATH       Source path to upload (default: SOURCE_MOUNT_PATH)
    -d, --dry-run           Test run without uploading
    --mount                 Mount drive before upload
    --unmount               Unmount drive after upload
    -h, --help              Show this help

EXAMPLES:
    # Upload from mounted device
    $0 --mount --unmount
    
    # Upload from specific path
    $0 --source /mnt/elements/Photos --mount
    
    # Dry run
    $0 --dry-run --mount

NOTES:
    - Run ./consolidate-folders.sh first to organize your files
    - This uploads recursively from a single entry point
    - Avoids worker pool deadlock issues
EOF
}

main() {
    local source_path="${SOURCE_MOUNT_PATH}"
    local dry_run=false
    local do_mount=false
    local do_unmount=false
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -s|--source)
                source_path="$2"
                shift 2
                ;;
            -d|--dry-run)
                dry_run=true
                shift
                ;;
            --mount)
                do_mount=true
                shift
                ;;
            --unmount)
                do_unmount=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    log_info "=========================================="
    log_info "Immich Simple Bulk Upload"
    log_info "=========================================="
    log_info "Source: $source_path"
    log_info "Server: $IMMICH_SERVER_URL"
    log_info "Log file: $LOG_FILE"
    log_info "=========================================="
    
    check_immich_go
    
    if [[ "$do_mount" == true ]]; then
        mount_drive || exit 1
    fi
    
    if [[ ! -d "$source_path" ]]; then
        log_error "Source path does not exist: $source_path"
        exit 1
    fi
    
    # Count files
    log_info "Counting media files..."
    local file_count=$(find "$source_path" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.mp4" -o -iname "*.mov" -o -iname "*.heic" \) 2>/dev/null | wc -l)
    log_info "Found approximately $file_count media files"
    
    # Build command
    local cmd=(
        immich-go upload from-folder
        --server="$IMMICH_SERVER_URL"
        --api-key="$IMMICH_API_KEY"
        --recursive=true
        --folder-as-album="${FOLDER_AS_ALBUM:-FOLDER}"
        --date-from-name=true
        --on-errors="${ON_ERRORS:-continue}"
        --client-timeout="${CLIENT_TIMEOUT:-2h}"
        --no-ui
    )
    
    # Add admin API key if provided and pause jobs is enabled
    if [[ "${PAUSE_IMMICH_JOBS:-false}" == "true" ]]; then
        if [[ -n "${IMMICH_ADMIN_API_KEY:-}" ]]; then
            cmd+=(--admin-api-key="$IMMICH_ADMIN_API_KEY")
            cmd+=(--pause-immich-jobs=true)
        else
            cmd+=(--pause-immich-jobs=false)
        fi
    else
        cmd+=(--pause-immich-jobs=false)
    fi
    
    if [[ "${FOLDER_AS_TAGS:-false}" == "true" ]]; then
        cmd+=(--folder-as-tags)
    fi
    
    if [[ "${SESSION_TAG:-false}" == "true" ]]; then
        cmd+=(--session-tag)
    fi
    
    if [[ -n "${CUSTOM_TAG:-}" ]]; then
        cmd+=(--tag="$CUSTOM_TAG")
    fi
    
    if [[ -n "${MANAGE_BURST:-}" ]]; then
        cmd+=(--manage-burst="$MANAGE_BURST")
    fi
    
    if [[ -n "${MANAGE_RAW_JPEG:-}" ]]; then
        cmd+=(--manage-raw-jpeg="$MANAGE_RAW_JPEG")
    fi
    
    if [[ "$dry_run" == true ]]; then
        cmd+=(--dry-run)
        log_warning "DRY RUN MODE - No files will be uploaded"
    fi
    
    cmd+=("$source_path")
    
    log_info "Starting upload..."
    log_info "Command: ${cmd[*]}"
    log_info ""
    
    local start_time=$(date +%s)
    
    # Run upload
    if "${cmd[@]}" 2>&1 | tee -a "$LOG_FILE"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        local hours=$((duration / 3600))
        local minutes=$(((duration % 3600) / 60))
        local seconds=$((duration % 60))
        
        log_success "=========================================="
        log_success "Upload completed successfully!"
        log_success "Duration: ${hours}h ${minutes}m ${seconds}s"
        log_success "=========================================="
    else
        log_error "Upload failed or completed with errors"
        log_error "Check log file: $LOG_FILE"
    fi
    
    if [[ "$do_unmount" == true ]]; then
        unmount_drive
    fi
}

trap 'log_error "Script interrupted"; exit 130' INT TERM

main "$@"
