#!/usr/bin/env bash
# =============================================================================
# docker-cleanup.sh — Remove bloated/unnecessary Docker resources
# =============================================================================
# Removes:
#   - Dangling images (untagged layers from old builds)
#   - Unused images (not referenced by any container)
#   - Stopped containers
#   - Unused networks
#   - Unused build cache
#
# Safe to run at any time. Does NOT remove:
#   - Images used by running containers
#   - Named volumes (data is preserved)
#
# Usage:
#   bash scripts/docker-cleanup.sh
#   bash scripts/docker-cleanup.sh --dry-run   (show what would be removed)
# =============================================================================
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Qacey Docker Cleanup                                     ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Show current state
info "Current Docker disk usage:"
docker system df
echo ""

if [[ "${DRY_RUN}" == "true" ]]; then
  warn "DRY RUN — showing what would be removed (no changes made)"
  echo ""
  info "Dangling images:"
  docker images -f "dangling=true" --format "  {{.ID}}\t{{.Size}}\t{{.CreatedAt}}"
  echo ""
  info "Unused images (not used by any container):"
  docker images --format "  {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -v "^  <none>"
  echo ""
  info "Build cache:"
  docker buildx du 2>/dev/null || docker system df --verbose 2>/dev/null | grep "Build Cache" || true
  exit 0
fi

# Step 1: Remove dangling images (safe — these are orphaned layers)
info "Removing dangling images..."
DANGLING=$(docker images -f "dangling=true" -q 2>/dev/null)
if [[ -n "${DANGLING}" ]]; then
  echo "${DANGLING}" | xargs docker rmi 2>/dev/null && success "Dangling images removed" || warn "Some dangling images could not be removed (may be in use)"
else
  success "No dangling images found"
fi

# Step 2: Remove stopped containers
info "Removing stopped containers..."
docker container prune -f 2>/dev/null && success "Stopped containers removed" || true

# Step 3: Remove unused networks
info "Removing unused networks..."
docker network prune -f 2>/dev/null && success "Unused networks removed" || true

# Step 4: Remove build cache (largest savings — safe to remove, rebuilds on next build)
info "Removing build cache..."
docker buildx prune -f 2>/dev/null && success "Build cache removed" || \
  docker builder prune -f 2>/dev/null && success "Build cache removed" || \
  warn "Could not remove build cache — try: docker builder prune -f"

# Step 5: Remove unused images (images not referenced by any container)
# This is more aggressive — only removes images with no running or stopped container using them
info "Removing unused images (not referenced by any container)..."
docker image prune -a -f 2>/dev/null && success "Unused images removed" || warn "Some images could not be removed"

echo ""
info "Docker disk usage after cleanup:"
docker system df
echo ""
success "Cleanup complete"
echo ""
