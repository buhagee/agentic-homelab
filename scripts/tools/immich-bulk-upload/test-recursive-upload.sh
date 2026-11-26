#!/bin/bash
#
# Test script to verify immich-go can handle multiple folders recursively
# This tests the claim that there's a "worker pool deadlock" bug
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/immich-bulk-upload.env"

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

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing immich-go Recursive Upload${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}This will do a DRY RUN to test if immich-go can scan all folders${NC}"
echo -e "${YELLOW}without hanging or stopping after a certain number of folders.${NC}"
echo ""

# Check if drive is mounted
if ! mountpoint -q "$SOURCE_MOUNT_PATH" 2>/dev/null; then
    echo -e "${RED}Drive not mounted at: $SOURCE_MOUNT_PATH${NC}"
    echo -e "${YELLOW}Run with --mount flag or mount manually first${NC}"
    exit 1
fi

# Count top-level folders
echo -e "${BLUE}Counting top-level folders...${NC}"
folder_count=$(find "$SOURCE_MOUNT_PATH" -mindepth 1 -maxdepth 1 -type d | wc -l)
echo -e "${GREEN}Found $folder_count top-level folders${NC}"
echo ""

# List first 20 folders
echo -e "${BLUE}First 20 folders:${NC}"
find "$SOURCE_MOUNT_PATH" -mindepth 1 -maxdepth 1 -type d | sort | head -20 | while read folder; do
    echo "  - $(basename "$folder")"
done
echo ""

# Run dry-run test
echo -e "${BLUE}Running DRY RUN test...${NC}"
echo -e "${YELLOW}Watch to see if it scans ALL folders or stops partway through${NC}"
echo ""

immich-go upload from-folder \
  --server="$IMMICH_SERVER_URL" \
  --api-key="$IMMICH_API_KEY" \
  --recursive=true \
  --dry-run \
  --log-level=INFO \
  "$SOURCE_MOUNT_PATH"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Test completed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Questions to answer:${NC}"
echo "1. Did it scan ALL $folder_count folders?"
echo "2. Did it stop/hang partway through?"
echo "3. How many folders did it actually process?"
echo ""
echo -e "${YELLOW}If it scanned everything successfully, there is NO bug.${NC}"
echo -e "${YELLOW}If it stopped after ~10-20 folders, then the bug exists.${NC}"
