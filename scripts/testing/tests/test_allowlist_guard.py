import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB = REPO_ROOT / "scripts" / "lib" / "allowlist.sh"


class AllowlistGuardTests(unittest.TestCase):
    def check(self, content):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        secrets = Path(tmp.name) / "secrets"
        secrets.mkdir()
        allowlist = secrets / "browser-oauth-allowed-emails.txt"
        if content is not None:
            allowlist.write_text(content, encoding="utf-8")
        return subprocess.run(
            ["bash", "-c", f'source "{LIB}"; require_allowlist "{tmp.name}"'],
            capture_output=True, text=True,
        )

    def test_missing_file_fails(self):
        result = self.check(None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("browser-oauth-allowed-emails.txt", result.stderr)

    def test_comment_only_file_fails(self):
        result = self.check("# nobody here\n\n")
        self.assertNotEqual(result.returncode, 0)

    def test_one_address_passes(self):
        result = self.check("# allowlist\nuser@example.com\n")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
