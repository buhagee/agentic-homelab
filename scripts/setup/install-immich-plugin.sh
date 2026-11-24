#!/bin/bash
# =============================================================================
# install-immich-plugin.sh — Install an Immich plugin
# =============================================================================
# Usage:
#   bash scripts/install-immich-plugin.sh <plugin-name> <github-repo-url>
# =============================================================================
set -euo pipefail

PLUGIN_NAME="$1"
PLUGIN_REPO="$2"

if [ -z "$PLUGIN_NAME" ] || [ -z "$PLUGIN_REPO" ]; then
    echo "Usage: $0 <plugin-name> <github-repo-url>"
    exit 1
fi

PLUGIN_DIR="/opt/qacey/immich-plugins/$PLUGIN_NAME"

echo "Installing Immich plugin: $PLUGIN_NAME"

# Create plugin directory
mkdir -p "$PLUGIN_DIR"

# Clone repo
echo "Cloning repository..."
git clone "$PLUGIN_REPO" "$PLUGIN_DIR"

# Create venv and install dependencies
echo "Creating virtual environment..."
cd "$PLUGIN_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create config template
cat > .env.example << 'EOF'
IMMICH_URL=https://photos.example.com
IMMICH_API_KEY=<create-in-immich-ui>
IMMICH_USER_EMAIL=user@example.com
EOF

echo "✓ Plugin installed at: $PLUGIN_DIR"
echo ""
echo "Next steps:"
echo "  1. Create API key in Immich UI (https://photos.example.com)"
echo "  2. Copy .env.example to .env and add API key:"
echo "     cd $PLUGIN_DIR && cp .env.example .env && nano .env"
echo "  3. Test with dry-run (check plugin README for exact command)"
