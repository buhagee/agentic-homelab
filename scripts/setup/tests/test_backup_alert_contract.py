import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP = REPO_ROOT / "scripts" / "maintenance" / "backup.sh"
DB_BACKUP = REPO_ROOT / "scripts" / "maintenance" / "db-backup.sh"
SERVICE = REPO_ROOT / "infrastructure" / "backup" / "qacey-backup.service"
TIMER = REPO_ROOT / "infrastructure" / "backup" / "qacey-backup.timer"


class BackupAlertContractTests(unittest.TestCase):
    def test_backup_uses_shared_alert_and_loader(self):
        text = BACKUP.read_text(encoding="utf-8")
        self.assertIn("scripts/lib/platform-env.sh", text)
        self.assertIn("scripts/lib/alert.sh", text)
        self.assertIn("send_alert", text)
        self.assertNotIn("telegram_alert", text)
        self.assertNotIn("api.telegram.org", text)

    def test_db_backup_alerts_on_error(self):
        text = DB_BACKUP.read_text(encoding="utf-8")
        self.assertIn("send_alert", text)
        self.assertIn("trap", text)
        self.assertIn("ERR", text)

    def test_service_wants_db_backup(self):
        text = SERVICE.read_text(encoding="utf-8")
        self.assertIn("Wants=qacey-db-backup.service", text)
        self.assertNotIn("Requires=qacey-db-backup.service", text)

    def test_timer_is_16_utc_and_persistent(self):
        text = TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 16:00:00", text)
        self.assertIn("Persistent=true", text)

    def test_stale_dump_check_is_present(self):
        text = BACKUP.read_text(encoding="utf-8")
        self.assertIn("MAX_DUMP_AGE_HOURS=2", text)
        self.assertIn("-mmin", text)
        self.assertIn("-size +100c", text)

    def test_backup_failure_paths_use_two_argument_fail(self):
        text = BACKUP.read_text(encoding="utf-8")
        for one_arg in (
            'send_alert "$mp is not mounted. Backup aborted."',
            'send_alert "SSD → HDD2 rsync failed',
            'send_alert "HDD1 → HDD2 rsync failed',
            'send_alert "restic repository check failed',
            'send_alert "restic B2 backup failed',
            'send_alert "restic retention prune failed',
        ):
            self.assertNotIn(one_arg, text)
        self.assertIn('fail "Qacey backup failed"', text)

    def test_db_backup_writes_temporary_files(self):
        text = DB_BACKUP.read_text(encoding="utf-8")
        self.assertIn('.sql.gz.tmp', text)
        self.assertIn('.sqlite3.gz.tmp', text)
        self.assertIn("mv \"$tmp\" \"$out\"", text)
        self.assertIn("trap cleanup EXIT", text)
        self.assertIn("db.sqlite3", text)

    def test_db_backup_includes_paperless(self):
        text = DB_BACKUP.read_text(encoding="utf-8")
        self.assertIn("paperless_$DATE.sqlite3.gz", text)
        self.assertIn("/mnt/ssd/qacey/paperless/data/db.sqlite3", text)
        self.assertNotIn("paperless-postgres", text)
        self.assertIn("paperless", BACKUP.read_text(encoding="utf-8"))

    def test_offsite_payload_is_small_and_excludes_heavy_state(self):
        text = BACKUP.read_text(encoding="utf-8")
        for path in (
            "/mnt/ssd/qacey/vaultwarden",
            "/mnt/ssd/qacey/paperless",
            "/mnt/ssd/qacey/traefik/certs",
            "/mnt/ssd/qacey/adguard/conf",
            "/mnt/ssd/qacey/hermes/skills",
            "/mnt/ssd/qacey/hermes/users",
            "/mnt/ssd/qacey/hermes/wife",
            "/mnt/ssd/qacey/hermes/annique",
            "/mnt/ssd/qacey/hermes/justin/data/memories",
        ):
            self.assertIn(path, text)
        self.assertNotIn("/mnt/ssd/qacey/postgres\n", text)
        self.assertNotIn("/mnt/ssd/qacey/hermes\n", text)
        self.assertNotIn("opencode-v2", text)

    def test_retention_and_repo_guard(self):
        text = BACKUP.read_text(encoding="utf-8")
        self.assertIn("--keep-last 2", text)
        self.assertIn("REPO_SOFT_LIMIT_BYTES", text)
        self.assertIn("REPO_TOTAL_LIMIT_BYTES", text)
        self.assertIn("payload_bytes", text)
        self.assertIn("restic --no-lock stats", text)
        self.assertIn("jq -r", text)


if __name__ == "__main__":
    unittest.main()
