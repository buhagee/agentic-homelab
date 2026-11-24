# Maintenance Scripts

Operational maintenance scripts for backup, cleanup, and service management.

## Backup Scripts

### backup.sh
Main backup script with two-phase approach.

**Phase 1: Local Mirror (always runs)**
- Mirrors `/mnt/hdd1` → `/mnt/hdd2` using rsync
- Incremental, preserves permissions
- Survives single drive failure

**Phase 2: Offsite Backup (optional)**
- Encrypts and uploads to Backblaze B2 using restic
- Only runs if all B2 variables are set in `.env` or `secrets/.env`
- Includes selected service state, the newest database dumps, platform `.env`,
  `secrets/.env`, `docker-compose.platform.yml`, and `versions.env`
- Incremental, deduplicated, encrypted

**Usage:**
```bash
bash maintenance/backup.sh
```

**Schedule:** Nightly via systemd timer at 16:00 UTC (02:00 AEST / 03:00 AEDT)

**Alerting:** failure emails use the shared SMTP helper (`scripts/lib/send_email.py`).

**Prerequisites:**
- `/mnt/hdd1` and `/mnt/hdd2` mounted
- For offsite: `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`, `B2_BUCKET`, `RESTIC_PASSWORD` in `.env`/`secrets/.env`
- SMTP values in `.env`/`secrets/.env` for failure emails

### verify-backup.sh
Checks the latest restic snapshot is less than 36 hours old and runs a sampled
repository integrity check.

**Usage:**
```bash
sudo bash maintenance/verify-backup.sh
sudo bash maintenance/verify-backup.sh --dry-run
```

**Schedule:** Daily at 18:00 UTC via `qacey-backup-verify.timer`.

**Alerting:** emails on a stale snapshot, missing repository, or failed check.

### db-backup.sh
Database backup script (PostgreSQL dumps plus the Paperless SQLite database).

**What it backs up:**
- Immich PostgreSQL database
- Paperless SQLite database
- Mnemo PostgreSQL databases

**Usage:**
```bash
bash maintenance/db-backup.sh
```

**Output:** SQL and `.sqlite3.gz` dumps in `/mnt/hdd1/qacey/db-backups/`

**Schedule:** Invoked by `qacey-db-backup.service` before the main backup.

### install-backup.sh
Installs backup systemd units.

**What it does:**
- Creates the nightly backup timer at 16:00 UTC
- Installs the DB and file backup services
- Installs the daily offsite verification timer at 18:00 UTC
- Configures log rotation
- Sets up backup alerting

**Usage:**
```bash
bash maintenance/install-backup.sh
```

**When to run:** Once during initial setup (or after cron changes)

### restore-drill.sh
Non-destructive restore drill for the latest Vaultwarden backup.

**What it does:**
- Restores `/mnt/ssd/qacey/vaultwarden` from the latest restic snapshot to `/tmp`
- Checks the SQLite database opens and counts users
- Starts a throwaway Vaultwarden container on `127.0.0.1:18080`
- Verifies `/alive`, then removes the container and temporary restore

**Usage:**
```bash
sudo bash maintenance/restore-drill.sh
# Optional different local port:
sudo RESTORE_PORT=18081 bash maintenance/restore-drill.sh
```

**What it does not touch:** the production Vaultwarden container, its data, or
the live database.

### restore-drill-immich.sh / restore-drill-paperless.sh
Immich restores the newest PostgreSQL dump into a throwaway container.
Paperless restores the newest SQLite backup into a temporary directory. Both
run a count query; production data is not mounted or stopped.

```bash
sudo bash maintenance/restore-drill-immich.sh
sudo bash maintenance/restore-drill-paperless.sh
```

The media check samples the HDD2 mirror only. Immich and Paperless media are
not offsite.

## Cleanup Scripts

### docker-cleanup.sh
Cleans up Docker resources.

**What it cleans:**
- Stopped containers
- Unused images
- Build cache
- Unused networks

It does **not** prune named volumes.

**Usage:**
```bash
bash maintenance/docker-cleanup.sh
```

**When to run:**
- When disk space is low
- After major Docker image updates
- Monthly maintenance

**Warning:** This does not remove volumes, but it can remove images and networks used by stopped stacks. Review `--dry-run` first.

### harden-hermes-data.sh
Restricts Hermes profile/session/memory files and managed script permissions.
The shared Hermes config keeps ended sessions for 400 days: enough for year-old
lookup with a small safety buffer, while preventing indefinite DB growth.

**Usage:**
```bash
bash maintenance/harden-hermes-data.sh
```

This operation never deletes data.

## Service Management

### restart-hermes.sh
Restarts Hermes agent containers.

**What it does:**
- Stops `hermes-justin` and `hermes-annique`
- Waits for clean shutdown
- Starts containers
- Verifies they're healthy

**Usage:**
```bash
bash maintenance/restart-hermes.sh
```

**When to run:**
- After config changes
- After skill updates
- When agents are unresponsive

## Monitoring Setup

### monitor-memory.sh
Collects container memory usage data (runs via cron). It logs only; it does not
clear caches or swap.

**Schedule:** Every 15 minutes  
**Data retention:** 4 weeks  
**Log file:** `/var/log/qacey/memory-usage.log`

**Manual run:**
```bash
bash maintenance/monitor-memory.sh
```

### analyze-memory.sh
Analyzes collected memory data.

**Usage:**
```bash
# Analyze last 7 days
bash maintenance/analyze-memory.sh 7

# Analyze last 30 days
bash maintenance/analyze-memory.sh 30
```

**Output:**
- Average/peak memory usage per container
- Over-allocated containers (< 50% usage)
- Under-allocated containers (> 80% usage)
- Optimization recommendations

**When to run:** After 30 days of data collection.

### crowdsec-repair.sh
Repairs CrowdSec configuration issues.

**What it fixes:**
- Bouncer registration issues
- LAPI connection problems
- Config file corruption
- Database issues

**Usage:**
```bash
bash maintenance/crowdsec-repair.sh
```

**When to run:**
- When CrowdSec bouncer fails
- After CrowdSec upgrades
- When seeing 403 errors from Traefik

## Maintenance Schedule

### Daily (Automated)
- `backup.sh` — 16:00 UTC (02:00 AEST / 03:00 AEDT) via systemd
- `db-backup.sh` — invoked by `qacey-db-backup.service` before `backup.sh`
- `platform-healthcheck.sh` — every 15 minutes via `qacey-healthcheck.timer`

### Weekly (Manual)
- `docker-cleanup.sh` — Free up disk space

### As Needed
- `restart-hermes.sh` — When agents need restart
- `crowdsec-repair.sh` — When CrowdSec has issues

## Repair Scripts

Check backup status:
```bash
# Check last backup
ls -lh /mnt/hdd2/qacey/

# Check backup logs
tail -f /var/log/qacey-backup.log

# Check restic snapshots (if using B2)
restic -r b2:qacey-backup-prod snapshots
```

Check disk usage:
```bash
df -h /mnt/hdd1 /mnt/hdd2
du -sh /mnt/hdd1/qacey/*
```

## Safety

- **Backup before cleanup**: Always run backup.sh before docker-cleanup.sh
- **Test restores**: Periodically test backup restoration
- **Monitor logs**: Check backup logs for errors
- **Disk space**: Keep at least 20% free on HDDs

## Troubleshooting

### Backup fails with "no space left"
```bash
# Check disk usage
df -h

# Clean up Docker
bash maintenance/docker-cleanup.sh

# Check for large files
du -sh /mnt/hdd1/qacey/* | sort -h
```

### Restic backup slow or failing
```bash
# Check B2 credentials
restic -r b2:qacey-backup-prod snapshots

# Prune old snapshots
restic -r b2:qacey-backup-prod forget --keep-daily 7 --keep-weekly 4 --prune
```

### Hermes won't restart
```bash
# Check logs
docker logs hermes-justin

# Force restart
docker stop hermes-justin hermes-annique
docker rm hermes-justin hermes-annique
bash start.sh
```
