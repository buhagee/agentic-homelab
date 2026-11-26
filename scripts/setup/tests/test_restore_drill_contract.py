import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MAINTENANCE = REPO_ROOT / "scripts" / "maintenance"
LIB = MAINTENANCE / "restore-drill-lib.sh"
IMMICH = MAINTENANCE / "restore-drill-immich.sh"
PAPERLESS = MAINTENANCE / "restore-drill-paperless.sh"
DOC = REPO_ROOT / "docs" / "operations" / "backup-restore.md"


class RestoreDrillContractTests(unittest.TestCase):
    def test_helper_is_non_destructive(self):
        text = LIB.read_text(encoding="utf-8")
        self.assertIn("docker run -d --rm", text)
        self.assertIn("127.0.0.1:", text)
        self.assertIn("pg_isready", text)
        self.assertIn("ON_ERROR_STOP", text)
        self.assertIn("gzip -t", text)
        self.assertIn("restore_drill_ensure_database", text)
        self.assertIn("createdb", text)

    def test_immich_drill_uses_throwaway_postgres(self):
        text = IMMICH.read_text(encoding="utf-8")
        self.assertIn("ghcr.io/immich-app/postgres", text)
        self.assertIn("restore_drill_latest_dump immich", text)
        self.assertIn("select count(*) from assets", text)
        self.assertIn("vectors\\.", text)
        self.assertIn("grep -vE", text)
        self.assertIn("for subdir in upload library thumbs encoded-video", text)
        self.assertNotIn("/mnt/ssd/qacey/postgres", text)

    def test_paperless_drill_restores_sqlite(self):
        text = PAPERLESS.read_text(encoding="utf-8")
        self.assertIn("paperless_*.sqlite3.gz", text)
        self.assertIn("PRAGMA integrity_check", text)
        self.assertIn("SELECT count(*) FROM documents_document", text)
        self.assertNotIn("postgres:", text)
        self.assertNotIn("/mnt/ssd/qacey/postgres", text)

    def test_docs_name_both_drills(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("restore-drill-immich.sh", text)
        self.assertIn("restore-drill-paperless.sh", text)
        self.assertIn("throwaway container", text)

    def test_shell_syntax(self):
        for script in (LIB, IMMICH, PAPERLESS):
            result = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{script}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
