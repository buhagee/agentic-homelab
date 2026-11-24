# Tools

One-off tools and utilities for specific tasks.

## Immich Bulk Upload

Tool for bulk uploading photos and videos from external drives to Immich.

**Location:** `tools/immich-bulk-upload/`

**Files:**
- `immich-bulk-upload.sh` — Main upload script
- `immich-bulk-upload.env` — Configuration (gitignored)
- `immich-bulk-upload.env.example` — Configuration template

**Quick Start:**
```bash
# 1. Copy config template
cp tools/immich-bulk-upload/immich-bulk-upload.env.example \
   tools/immich-bulk-upload/immich-bulk-upload.env

# 2. Edit config (add API key)
nano tools/immich-bulk-upload/immich-bulk-upload.env

# 3. Run dry run
bash tools/immich-bulk-upload/immich-bulk-upload.sh --dry-run

# 4. Run actual upload
bash tools/immich-bulk-upload/immich-bulk-upload.sh
```

**Purpose:** Upload large collections of media files (100k+ files) from external drives to Immich user accounts.

**Features:**
- ✅ Dry run mode (preview before uploading)
- ✅ Selective upload (only photos/videos, skip documents)
- ✅ Read-only mount (cannot modify source)
- ✅ Resumable (safe to interrupt with Ctrl+C)
- ✅ Duplicate detection (Immich skips duplicates)
- ✅ Progress tracking (real-time speed and ETA)
- ✅ Error logging (all errors logged to file)
- ✅ Metadata preservation (EXIF, timestamps, GPS)

**Usage:**
```bash
# Dry run (preview only)
bash tools/immich-bulk-upload.sh --dry-run

# Actual upload
bash tools/immich-bulk-upload.sh
```

**Configuration:**
Edit `tools/immich-bulk-upload/immich-bulk-upload.env`:
```bash
IMMICH_SERVER_URL=https://photos.example.com
IMMICH_API_KEY=your-api-key-here
IMMICH_USER_EMAIL=user@example.com
SOURCE_DEVICE=/dev/sde1
SOURCE_MOUNT_PATH=/mnt/elements
```

**Prerequisites:**
1. Node.js 24+ installed
2. Immich CLI installed: `sudo npm install -g @immich/cli`
3. API key generated in Immich web UI
4. External drive connected

**Setup:**
```bash
# 1. Install Immich CLI
sudo npm install -g @immich/cli

# 2. Copy config template
cp tools/immich-bulk-upload/immich-bulk-upload.env.example \
   tools/immich-bulk-upload/immich-bulk-upload.env

# 3. Edit config
nano tools/immich-bulk-upload/immich-bulk-upload.env
# Add your IMMICH_API_KEY

# 4. Run dry run
bash tools/immich-bulk-upload/immich-bulk-upload.sh --dry-run
```

**Expected Output:**
```
========================================
  Immich Bulk Upload
========================================

Checking prerequisites...
✓ Immich CLI installed: 2.7.5
✓ API key found
✓ Server reachable at https://photos.example.com
✓ Source device found: /dev/sde1
✓ Log directory ready

Checking drive mount...
✓ Drive mounted at /mnt/elements

Counting media files (this may take a few minutes)...
✓ Found 105432 photos
✓ Found 5076 videos
✓ Total: 110508 media files

========================================
  DRY RUN MODE
========================================
Source: /mnt/elements
Server: https://photos.example.com
Log file: logs/immich-upload-20260523-HHMMSS.log

[Immich CLI output showing what would be uploaded]

========================================
  UPLOAD SUMMARY
========================================
✓ Dry run completed successfully
```

**Actual Upload:**
```bash
bash tools/immich-bulk-upload/immich-bulk-upload.sh

# Confirm when prompted
Proceed with upload? Type 'yes' to continue: yes

# Upload will run (8-16 hours for ~110k files)
# Press Ctrl+C to safely interrupt (can resume later)
```

**Logs:**
- Location: `logs/immich-upload-YYYYMMDD-HHMMSS.log`
- Contains: All upload activity, errors, progress

**Resuming:**
If interrupted, just run the script again:
```bash
bash tools/immich-bulk-upload/immich-bulk-upload.sh
```
Immich CLI automatically skips already-uploaded files.

**Troubleshooting:**

*Error: "Configuration file not found"*
```bash
cp tools/immich-bulk-upload.env.example tools/immich-bulk-upload.env
nano tools/immich-bulk-upload.env
```

*Error: "IMMICH_API_KEY not set"*
- Generate API key in Immich web UI
- Add to `tools/immich-bulk-upload.env`

*Error: "Source device /dev/sde1 not found"*
```bash
# Check connected drives
lsblk

# Update SOURCE_DEVICE in config
nano tools/immich-bulk-upload.env
```

*Upload is very slow*
- Check network speed
- Check server disk I/O
- Expected: 50-100 MB/s (local network)

**Use Cases:**
- Migrating photo libraries to Immich
- Bulk uploading from external hard drives
- Importing family photo collections
- One-time large uploads

**Documentation:**
- Full guide: `aidlc-docs/construction/u-15/USAGE.md`
- Quick start: `aidlc-docs/construction/u-15/QUICK-START.md`
- Design: `aidlc-docs/construction/u-15/infrastructure-design.md`

## Adding New Tools

To add a new tool:

1. Create a subdirectory: `mkdir tools/my-tool`
2. Add the script: `tools/my-tool/my-tool.sh`
3. Make it executable: `chmod +x tools/my-tool/my-tool.sh`
4. Add config template if needed: `tools/my-tool/my-tool.env.example`
5. Document it in this README
6. Add to `.gitignore` if it has secrets: `tools/my-tool/my-tool.env`

**Example structure:**
```
tools/
└── my-tool/
    ├── my-tool.sh
    ├── my-tool.env
    └── my-tool.env.example
```

## Notes

- Tools are standalone (don't depend on platform services)
- Tools have their own config files (not in main `.env`)
- Tools are for one-off or infrequent tasks
- Tools should be well-documented (usage, prerequisites, examples)
