import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "setup" / "isolate-agent-secrets.sh"
BACKUP = REPO_ROOT / "scripts" / "maintenance" / "backup.sh"
DOC = REPO_ROOT / "docs" / "operations" / "backup-restore.md"


class AgentSecretIsolationTests(unittest.TestCase):
    def test_script_moves_secrets_outside_projects(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/.config/qacey-secrets", text)
        self.assertIn("--dry-run", text)
        self.assertIn("ln -s", text)
        self.assertIn('[[ "$(id -un)" == "buhagiar" ]]', text)
        self.assertNotIn("sudo", text)

    def test_backup_includes_isolated_secret_directory(self):
        text = BACKUP.read_text(encoding="utf-8")
        self.assertIn("getent passwd", text)

    def test_restore_docs_include_isolated_directory(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("/srv/agentic-homelab-secrets", text)
        self.assertIn("Restore", text)

    def test_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
