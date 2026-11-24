# Backup and restore

Nightly backup runs at **16:00 UTC**:

1. `qacey-db-backup.service` writes logical PostgreSQL dumps to
   `/mnt/hdd1/qacey/db-backups/`.
2. `qacey-backup.service` mirrors SSD/HDD1 to HDD2, then writes the offsite
   restic snapshot.
3. `qacey-backup-verify.timer` checks at **18:00 UTC** that the newest snapshot
   is under 24 hours old and runs `restic check --read-data-subset=1/50`.

## What is offsite

- Selected service state under `/mnt/ssd/qacey`, including Vaultwarden,
  Paperless, Traefik certificates, CrowdSec, AdGuard, WireGuard, Home
  Assistant, Hermes profiles, and OpenCode state.
- The newest Immich and Mnemo PostgreSQL dumps plus the Paperless SQLite backup.
- Platform `.env`, `secrets/.env`, `docker-compose.platform.yml`, and
  `versions.env`.
- The isolated secret directory `/srv/agentic-homelab-secrets`.
- Immich, Nextcloud, and Paperless media are not offsite. They exist on
  HDD1 and the HDD2 mirror only.

Restic encrypts everything. Keep `RESTIC_PASSWORD` in a password manager
outside the host; without it the offsite repository cannot be restored.

## Verify

```sh
sudo bash scripts/maintenance/backup.sh --verify-offsite
sudo bash scripts/maintenance/verify-backup.sh
systemctl list-timers qacey-backup.timer qacey-backup-verify.timer --no-pager
```

`verify-backup.sh` emails on a stale snapshot, missing repository, or failed
sampled check.

## Restore Vaultwarden

Non-destructive drill:

```sh
sudo bash scripts/maintenance/restore-drill.sh
```

It restores the latest Vaultwarden path from restic to `/tmp`, opens the SQLite
database read-only, starts a throwaway container, and checks `/alive`.
Production is not touched.

## Restore platform config and secrets

```sh
sudo bash
cd /srv/agentic-homelab
source scripts/lib/platform-env.sh
load_platform_env "$PWD"
export B2_ACCOUNT_ID B2_ACCOUNT_KEY
export RESTIC_REPOSITORY="b2:${B2_BUCKET}:/qacey"
export RESTIC_PASSWORD

restic snapshots --latest 5
restic restore latest --target /tmp/qacey-restore \
  --include /srv/agentic-homelab/.env \
  --include /srv/agentic-homelab/secrets/.env \
  --include /srv/agentic-homelab-secrets \
  --include /srv/agentic-homelab/docker-compose.platform.yml \
  --include /srv/agentic-homelab/versions.env
```

The `.env` and `secrets/.env` paths are symlinks after isolation. Restore
`/srv/agentic-homelab-secrets` as well; reviewing only the symlinks is
not enough.

## Restore a PostgreSQL dump

Restore the matching dump into a scratch database first, not production:

```sh
ls -lt /mnt/hdd1/qacey/db-backups/
gunzip -c /mnt/hdd1/qacey/db-backups/immich_YYYY-MM-DD.sql.gz \
  | docker exec -i immich-postgres psql -U immich -d immich
```

Use `mnemo` with `mnemo_justin` or `mnemo_annique` for Mnemo. A production
restore needs the owning application stopped or a maintenance window.

## Paperless is SQLite

Paperless currently runs on
`/mnt/ssd/qacey/paperless/data/db.sqlite3`. The `paperless-postgres` service is
empty and unused because the compose uses unsupported `PAPERLESS_DATABASE_*`
names. `db-backup.sh` takes a SQLite-safe backup with the Python backup API.

Do not switch Paperless to Postgres without a data migration plan.

## Restore Immich and Paperless

Immich restores the newest PostgreSQL dump into a throwaway container.
Paperless decompresses the newest SQLite backup into a temporary directory.
Neither drill mounts production data or stops production services.

```sh
sudo bash scripts/maintenance/restore-drill-immich.sh
sudo bash scripts/maintenance/restore-drill-paperless.sh
```

The Immich drill runs a table/count query and samples the HDD2 media mirror
under `upload/`, `library/`, `thumbs/`, or `encoded-video/`. The Paperless
drill runs `PRAGMA integrity_check`, counts documents, and checks the HDD2
media mirror. The throwaway container or temporary directory is removed on
exit.

## Restore media

Immich, Nextcloud, and Paperless media are restored from the HDD2 mirror:

```text
/mnt/hdd2/qacey/hdd1-mirror/immich
/mnt/hdd2/qacey/hdd1-mirror/nextcloud
/mnt/hdd2/qacey/ssd-mirror/paperless
```

The mirror is not offsite. A fire, theft, or ransomware event can destroy both
the primary and the mirror.

## Known gaps

- The Immich and Paperless database drills passed on 2026-11-20. Full media
  restore was not tested; only a mirror sample was checked.
- Home Assistant and Vaultwarden are captured as live SQLite files; the
  Vaultwarden drill passes, but a SQLite-safe dump is not part of the nightly
  payload.
- B2 object lock/immutability is not enabled. Use a bucket-scoped key and keep
  a deletion credential off the host.
