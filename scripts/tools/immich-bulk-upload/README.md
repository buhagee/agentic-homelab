# Immich Bulk Upload Tool

Reliable batch upload script for uploading large media collections from external hard drives to Immich using [immich-go](https://github.com/simulot/immich-go).

## Features

- ✅ **No folder limits** - Upload unlimited folders recursively
- ✅ **Automatic drive mounting/unmounting**
- ✅ **Progress tracking** - Resume interrupted uploads
- ✅ **Error handling** - Continue on errors or stop
- ✅ **Dry-run mode** - Test before uploading
- ✅ **Batch processing** - Process folders in configurable batches
- ✅ **Comprehensive logging** - Track all operations
- ✅ **Album organization** - Auto-create albums from folder structure
- ✅ **Tag support** - Add custom tags and session tags
- ✅ **RAW+JPEG handling** - Stack related files
- ✅ **Burst photo management** - Stack burst sequences

## Prerequisites

1. **immich-go** installed and in PATH
   ```bash
   # Download from releases
   wget https://github.com/simulot/immich-go/releases/latest/download/immich-go_Linux_x86_64.tar.gz
   tar -xzf immich-go_Linux_x86_64.tar.gz
   sudo mv immich-go /usr/local/bin/
   
   # Or install with Go
   go install github.com/simulot/immich-go@latest
   ```

2. **Immich server** running and accessible

3. **API key** generated in Immich (Account Settings → API Keys)

## ⚠️ Important: Use Sequential Script

Due to a worker pool deadlock bug in immich-go v0.27.0, **use the sequential script** for reliable uploads:

```bash
./immich-bulk-upload-sequential.sh --mount --unmount
```

The original `immich-bulk-upload.sh` may hang after scanning only 10-15 folders due to a concurrency bug.

## Quick Start

### 1. Configure Environment

Copy the example configuration:
```bash
cp immich-bulk-upload.env.example immich-bulk-upload.env
```

Edit `immich-bulk-upload.env`:
```bash
# Required settings
IMMICH_SERVER_URL=http://localhost:2283
IMMICH_API_KEY=your-api-key-here
SOURCE_DEVICE=/dev/sde1
SOURCE_MOUNT_PATH=/mnt/elements

# Optional settings (with defaults)
CONCURRENT_TASKS=8              # Parallel upload threads (1-20)
FOLDER_AS_ALBUM=FOLDER          # Create albums: FOLDER, PATH, or NONE
FOLDER_AS_TAGS=false            # Use folder structure as tags
ON_ERRORS=continue              # Error handling: stop, continue, or N
CLIENT_TIMEOUT=30m              # Server timeout
PAUSE_IMMICH_JOBS=true          # Pause server jobs during upload
BATCH_SIZE=20                   # Folders per batch (batch mode only)
BATCH_DELAY=5                   # Seconds between batches (optional)
```

### 2. Make Script Executable

```bash
chmod +x immich-bulk-upload.sh
```

### 3. Run Upload

**Recommended: Sequential mode (most reliable)**
```bash
./immich-bulk-upload-sequential.sh --mount --unmount
```

This will:
- Mount your external drive
- Upload each top-level folder one at a time (avoids deadlock)
- Show progress per folder
- Unmount the drive when done

**Alternative: Resume from specific folder**
```bash
./immich-bulk-upload-sequential.sh --skip-to "Photos  2021" --mount
```

## Upload Modes

### Recursive Mode (Recommended)

Upload the entire drive in one operation. immich-go handles all folders automatically.

```bash
./immich-bulk-upload.sh --mode recursive --mount --unmount
```

**Pros:**
- Simplest approach
- No folder limits
- Efficient resource usage
- Automatic progress tracking by immich-go

**Use when:**
- You want to upload everything
- You trust immich-go's error handling
- You want the fastest upload

### Batch Mode

Process top-level folders in configurable batches.

```bash
./immich-bulk-upload.sh --mode batch --mount --unmount
```

**Pros:**
- More granular control
- Can pause between batches
- Easier to track progress per folder
- Can resume specific batches

**Use when:**
- You want to process folders in chunks
- You need breaks between uploads
- You want to monitor progress per folder group

## Usage Examples

### Basic Upload
```bash
# Recursive upload (recommended)
./immich-bulk-upload.sh --mode recursive --mount --unmount

# Batch upload
./immich-bulk-upload.sh --mode batch --mount
```

### Dry Run (Test First)
```bash
# Test what would be uploaded without actually uploading
./immich-bulk-upload.sh --dry-run --mount
```

### Upload Specific Subfolder
```bash
# Upload only a specific folder
./immich-bulk-upload.sh --source /mnt/elements/Photos/2024 --mount
```

### Resume After Interruption
```bash
# Just run the same command again
# immich-go automatically skips already uploaded files
./immich-bulk-upload.sh --mode recursive --mount --unmount
```

### Manual Drive Management
```bash
# Mount manually first
sudo mount /dev/sde1 /mnt/elements

# Upload without auto-mount/unmount
./immich-bulk-upload.sh --mode recursive

# Unmount manually when done
sudo umount /mnt/elements
```

## Configuration Options

### Environment Variables

Set these in `immich-bulk-upload.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `IMMICH_SERVER_URL` | *required* | Immich server URL (use localhost to bypass Traefik for large files) |
| `IMMICH_API_KEY` | *required* | Immich API key |
| `SOURCE_DEVICE` | *required* | Source drive device (e.g., `/dev/sde1`) |
| `SOURCE_MOUNT_PATH` | *required* | Mount point for source drive |
| `CONCURRENT_TASKS` | `8` | Parallel upload threads (1-20) |
| `FOLDER_AS_ALBUM` | `FOLDER` | Album creation: `FOLDER`, `PATH`, or `NONE` |
| `FOLDER_AS_TAGS` | `false` | Use folder structure as tags |
| `ON_ERRORS` | `continue` | Error handling: `stop`, `continue`, or number |
| `CLIENT_TIMEOUT` | `30m` | Server call timeout |
| `PAUSE_IMMICH_JOBS` | `true` | Pause server jobs during upload |
| `BATCH_SIZE` | `20` | Folders per batch (batch mode only) |
| `BATCH_DELAY` | - | Seconds to wait between batches |
| `SESSION_TAG` | - | Tag uploads with session timestamp |
| `CUSTOM_TAG` | - | Add custom tag to all uploads |
| `MANAGE_BURST` | - | Handle burst photos: `Stack` |
| `MANAGE_RAW_JPEG` | - | Handle RAW+JPEG: `StackCoverRaw` |

### Command-Line Options

```bash
./immich-bulk-upload.sh [OPTIONS]

OPTIONS:
    -m, --mode MODE         Upload mode: recursive (default), batch
    -s, --source PATH       Source path to upload
    -d, --dry-run           Test run without uploading
    --mount                 Mount drive before upload
    --unmount               Unmount drive after upload
    --no-unmount            Don't unmount after upload (default)
    -h, --help              Show help message
```

## Performance Tuning

### For Large Collections (100k+ photos)
```bash
CONCURRENT_TASKS=4
CLIENT_TIMEOUT=60m
ON_ERRORS=continue
```

### For Fast Networks
```bash
CONCURRENT_TASKS=16
CLIENT_TIMEOUT=30m
```

### For Slow/Unstable Networks
```bash
CONCURRENT_TASKS=1
CLIENT_TIMEOUT=120m
ON_ERRORS=continue
```

### For Maximum Speed (Gigabit LAN)
```bash
CONCURRENT_TASKS=20
CLIENT_TIMEOUT=20m
PAUSE_IMMICH_JOBS=true
```

## Album Organization

### Option 1: Folder Name as Album
```bash
FOLDER_AS_ALBUM=FOLDER
```
- `/Photos/Vacation` → Album: "Vacation"
- `/Photos/2024/Summer` → Album: "Summer"

### Option 2: Full Path as Album
```bash
FOLDER_AS_ALBUM=PATH
```
- `/Photos/Vacation` → Album: "Photos / Vacation"
- `/Photos/2024/Summer` → Album: "Photos / 2024 / Summer"

### Option 3: No Albums
```bash
FOLDER_AS_ALBUM=NONE
```
- All photos uploaded without album organization

### Option 4: Single Album for Everything
```bash
FOLDER_AS_ALBUM=NONE
# Then in env file, add:
# (This requires modifying the script to support --into-album)
```

## Logging

Logs are saved to `logs/upload-YYYYMMDD-HHMMSS.log`

View logs in real-time:
```bash
tail -f logs/upload-*.log
```

Check for errors:
```bash
grep ERROR logs/upload-*.log
```

## Troubleshooting

### Drive Not Mounting
```bash
# Check if device exists
lsblk

# Check if already mounted
mount | grep /mnt/elements

# Try manual mount
sudo mount /dev/sde1 /mnt/elements
```

### Upload Stalls or Times Out
```bash
# Increase timeout
CLIENT_TIMEOUT=120m

# Reduce concurrent tasks
CONCURRENT_TASKS=2
```

### Server Overloaded
```bash
# Pause Immich jobs during upload
PAUSE_IMMICH_JOBS=true

# Reduce concurrent tasks
CONCURRENT_TASKS=4
```

### Duplicate Files
immich-go automatically detects and skips duplicates based on file hash. Re-running the script is safe.

### Permission Errors
```bash
# Ensure drive is readable
sudo chmod -R a+rX /mnt/elements

# Or run script with sudo (not recommended)
sudo ./immich-bulk-upload.sh --mode recursive --mount --unmount
```

## ⚠️ Known Issue: Worker Pool Deadlock

**UPDATE**: There is a concurrency bug in immich-go v0.27.0 that causes it to stop scanning after processing some folders.

### The Problem
- immich-go uses a worker pool for concurrent directory scanning
- When all workers are busy scanning directories, they can't process new subdirectory scan requests
- This creates a **deadlock** where the process hangs
- Result: Only a subset of folders get scanned (typically 10-15 out of many)

### The Solution
Use the **sequential upload script** (`immich-bulk-upload-sequential.sh`) which processes folders one at a time:

```bash
./immich-bulk-upload-sequential.sh --mount --unmount
```

This script:
- ✅ Processes each top-level folder individually
- ✅ Avoids the worker pool deadlock
- ✅ Provides progress tracking per folder
- ✅ Can resume from a specific folder if interrupted
- ✅ Shows file counts per folder

### Why No 20-Folder Limit?

The immich-go tool has **no intentional folder scanning limit**. The "20" refers to:
- `--concurrent-tasks` maximum (parallel upload threads)
- This is a performance limit, not a folder count limit

The tool **should** handle:
- ✅ Unlimited folders
- ✅ Recursive scanning to any depth
- ✅ Millions of files
- ✅ Multiple paths in one command

But due to the worker pool deadlock bug, use the sequential script for reliability.

## Advanced Usage

### Upload Multiple Specific Folders
```bash
# Edit the script or run immich-go directly
immich-go upload from-folder \
  --server="$IMMICH_SERVER_URL" \
  --api-key="$IMMICH_API_KEY" \
  --recursive=true \
  /mnt/elements/Photos/2020 \
  /mnt/elements/Photos/2021 \
  /mnt/elements/Photos/2022
```

### Use Shell Glob Patterns
```bash
# Upload all folders matching pattern
immich-go upload from-folder \
  --server="$IMMICH_SERVER_URL" \
  --api-key="$IMMICH_API_KEY" \
  --recursive=true \
  /mnt/elements/Photos/202*
```

### Filter by Date Range
```bash
# Add to env file or modify script
--date-range=2020-01-01,2024-12-31
```

### Filter by File Type
```bash
# Add to env file or modify script
--include-extensions=.jpg,.png,.heic
--exclude-extensions=.gif,.bmp
```

## Security Notes

1. **API Key Security**
   - Never commit `immich-bulk-upload.env` to git
   - It's already in `.gitignore`
   - Rotate API keys periodically

2. **Localhost vs Remote URL**
   - Use `http://localhost:2283` to bypass Traefik for large uploads
   - Use `https://your-domain.com` for remote uploads
   - Localhost is faster for local uploads (no proxy overhead)

3. **Drive Permissions**
   - Script may need sudo for mounting
   - Consider adding mount rules to `/etc/fstab` for automatic mounting

## Support

- **immich-go**: https://github.com/simulot/immich-go
- **Immich**: https://github.com/immich-app/immich
- **Issues**: Check logs in `logs/` directory

## License

This script is provided as-is for use with Immich and immich-go.
