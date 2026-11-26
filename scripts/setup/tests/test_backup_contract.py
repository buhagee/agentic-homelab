import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MAINTENANCE = REPO_ROOT / "scripts" / "maintenance"
BACKUP_UNITS = REPO_ROOT / "infrastructure" / "backup"
BACKUP = MAINTENANCE / "backup.sh"
VERIFY = MAINTENANCE / "verify-backup.sh"
INSTALL = MAINTENANCE / "install-backup.sh"
DB_BACKUP = MAINTENANCE / "db-backup.sh"
RESTORE_DOC = REPO_ROOT / "docs" / "operations" / "backup-restore.md"


class BackupConfigContractTests(unittest.TestCase):
    def test_backup_includes_platform_config_and_secrets(self):
        text = BACKUP.read_text(encoding="utf-8")
        for relative in (
            "${PLATFORM_DIR}/.env",
            "${PLATFORM_DIR}/secrets/.env",
            "${PLATFORM_DIR}/docker-compose.platform.yml",
            "${PLATFORM_DIR}/versions.env",
        ):
            self.assertIn(relative, text)

    def test_backup_resolves_deploy_secrets_and_allowlist(self):
        text = BACKUP.read_text(encoding="utf-8")
        self.assertIn("getent passwd", text)
        self.assertIn("secrets/browser-oauth-allowed-emails.txt", text)

    def test_db_backup_uses_paperless_sqlite_and_restic_finds_it(self):
        db_text = DB_BACKUP.read_text(encoding="utf-8")
        backup_text = BACKUP.read_text(encoding="utf-8")
        self.assertIn("dump_sqlite", db_text)
        self.assertIn("paperless_$DATE.sqlite3.gz", db_text)
        self.assertIn("/mnt/ssd/qacey/paperless/data/db.sqlite3", db_text)
        self.assertNotIn("dump_postgres paperless-postgres", db_text)
        self.assertIn('*.sqlite3.gz', backup_text)

    def test_backup_failure_reason_is_logged(self):
        text = BACKUP.read_text(encoding="utf-8")
        self.assertIn('echo "ERROR: ${subject}', text)

    def test_verify_script_checks_age_and_repository(self):
        text = VERIFY.read_text(encoding="utf-8")
        self.assertIn("MAX_AGE_HOURS", text)
        self.assertIn("restic snapshots --json --latest 1", text)
        self.assertIn("restic check --read-data-subset=1/50", text)
        self.assertIn("send_alert", text)

    def test_verify_units_and_installer_are_wired(self):
        service = (BACKUP_UNITS / "qacey-backup-verify.service").read_text(encoding="utf-8")
        timer = (BACKUP_UNITS / "qacey-backup-verify.timer").read_text(encoding="utf-8")
        installer = INSTALL.read_text(encoding="utf-8")
        self.assertIn("verify-backup.sh", service)
        self.assertIn("OnCalendar=*-*-* 18:00:00", timer)
        self.assertIn("qacey-backup-verify.service", installer)
        self.assertIn("qacey-backup-verify.timer", installer)
        self.assertIn("systemctl enable qacey-backup-verify.timer", installer)

    def test_restore_documentation_names_the_gaps(self):
        text = RESTORE_DOC.read_text(encoding="utf-8")
        self.assertIn("The Immich and Paperless database drills passed", text)
        self.assertIn("not offsite", text)
        self.assertIn("RESTIC_PASSWORD", text)

    def test_shell_syntax(self):
        for script in (BACKUP, VERIFY, INSTALL):
            result = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{script}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
