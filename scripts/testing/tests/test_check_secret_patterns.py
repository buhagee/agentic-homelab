import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "testing"))
import check_secret_patterns


class SecretPatternTests(unittest.TestCase):
    def scan(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text(content, encoding="utf-8")
            return check_secret_patterns.find_violations([path])

    def test_flags_github_token(self):
        self.assertTrue(self.scan("token ghp_" + "a" * 36))

    def test_flags_private_key(self):
        self.assertTrue(self.scan("-----BEGIN " + "OPENSSH PRIVATE KEY-----"))

    def test_flags_crowdsec_lapi_key(self):
        self.assertTrue(self.scan("crowdsecLapiKey: \"" + "a" * 64 + "\""))

    def test_ignores_image_digest(self):
        self.assertEqual(
            self.scan("image: redis@sha256:" + "a" * 64), []
        )

    def test_ignores_placeholders(self):
        self.assertEqual(
            self.scan("API_KEY=<create-in-ui>\nTOKEN=CHANGE_ME"), []
        )


if __name__ == "__main__":
    unittest.main()
