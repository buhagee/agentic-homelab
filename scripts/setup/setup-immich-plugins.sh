#!/bin/bash
# =============================================================================
# setup-immich-plugins.sh — Setup all Tier 1 Immich plugins
# =============================================================================
# Installs folder-album-creator and auto-stack plugins
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Setting up Immich plugins..."
echo ""

# Create base directory
echo "Creating plugin directories..."
mkdir -p /opt/qacey/immich-plugins
mkdir -p /var/log/immich-plugins

# Install Tier 1 plugins
echo ""
echo "=== Installing folder-album-creator ==="
bash "$SCRIPT_DIR/install-immich-plugin.sh" \
    folder-album-creator \
    https://github.com/Salvoxia/immich-folder-album-creator

echo ""
echo "=== Installing auto-stack ==="
bash "$SCRIPT_DIR/install-immich-plugin.sh" \
    auto-stack \
    https://github.com/tenekev/immich-auto-stack

# Create master README
echo ""
echo "Creating master README..."
cat > /opt/qacey/immich-plugins/README.md << 'EOF'
# Immich Plugins

## Installed Plugins

### 1. Immich Folder Album Creator
- **Location:** `/opt/qacey/immich-plugins/folder-album-creator/`
- **Purpose:** Create albums from folder structure
- **Repository:** https://github.com/Salvoxia/immich-folder-album-creator
- **Usage:**
  ```bash
  cd /opt/qacey/immich-plugins/folder-album-creator
  source venv/bin/activate
  python main.py --dry-run  # Test mode
  python main.py            # Actual run
  ```
- **Schedule:** Daily at 2:00 AM (cron)
- **Logs:** `/var/log/immich-plugins/folder-album.log`

### 2. Immich Auto Stack
- **Location:** `/opt/qacey/immich-plugins/auto-stack/`
- **Purpose:** Automatically stack similar photos
- **Repository:** https://github.com/tenekev/immich-auto-stack
- **Usage:**
  ```bash
  cd /opt/qacey/immich-plugins/auto-stack
  source venv/bin/activate
  python stack.py --dry-run  # Test mode
  python stack.py            # Actual run
  ```
- **Schedule:** Daily at 3:00 AM (cron)
- **Logs:** `/var/log/immich-plugins/auto-stack.log`

## API Keys

Each plugin needs its own Immich API key:
1. Open Immich UI: https://photos.example.com
2. Go to Account Settings → API Keys
3. Create new key with description (e.g., "folder-album-creator")
4. Copy key to plugin's `.env` file

## Configuration

For each plugin:
```bash
cd /opt/qacey/immich-plugins/<plugin-name>
cp .env.example .env
nano .env  # Add your API key
```

## Testing

Always test with `--dry-run` first:
```bash
cd /opt/qacey/immich-plugins/folder-album-creator
source venv/bin/activate
python main.py --dry-run
```

## Scheduling

Plugins are scheduled via cron. See `/etc/cron.d/immich-plugins` for current schedule.

To create cron jobs:
```bash
sudo nano /etc/cron.d/immich-plugins
```

Example cron configuration:
```
# Folder Album Creator - Daily at 2:00 AM
0 2 * * * buhagiar cd /opt/qacey/immich-plugins/folder-album-creator && venv/bin/python main.py >> /var/log/immich-plugins/folder-album.log 2>&1

# Auto Stack - Daily at 3:00 AM
0 3 * * * buhagiar cd /opt/qacey/immich-plugins/auto-stack && venv/bin/python stack.py >> /var/log/immich-plugins/auto-stack.log 2>&1
```

## Logs

Plugin logs are stored in `/var/log/immich-plugins/`:
```bash
tail -f /var/log/immich-plugins/folder-album.log
tail -f /var/log/immich-plugins/auto-stack.log
```

## Updating Plugins

To update a plugin:
```bash
cd /opt/qacey/immich-plugins/<plugin-name>
git pull
source venv/bin/activate
pip install --upgrade -r requirements.txt
```
EOF

echo ""
echo "✓ Immich plugins setup complete"
echo ""
echo "Next steps:"
echo "  1. Create API keys in Immich UI for each plugin"
echo "  2. Configure .env files:"
echo "     cd /opt/qacey/immich-plugins/folder-album-creator && cp .env.example .env && nano .env"
echo "     cd /opt/qacey/immich-plugins/auto-stack && cp .env.example .env && nano .env"
echo "  3. Test each plugin with --dry-run (see README for commands)"
echo "  4. Setup cron jobs: sudo nano /etc/cron.d/immich-plugins"
echo ""
echo "Documentation: /opt/qacey/immich-plugins/README.md"
