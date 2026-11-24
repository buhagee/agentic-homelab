import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_EXCLUDES = (
    "aidlc/", "aidlc-docs/", "docs/reviews/", "docs/superpowers/",
)
FORBIDDEN_TRACKED = (
    "infrastructure/browser-oauth-allowed-emails.txt",
    "infrastructure/platform-admin-emails.txt",
    "infrastructure/traefik/config/dynamic/middlewares.yml",
    "infrastructure/traefik/config/dynamic/adguard.yml",
    "infrastructure/traefik/config/dynamic/homeassistant.yml",
)


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.splitlines() if p]


def snapshot_files():
    return [p for p in tracked_files() if not p.startswith(SNAPSHOT_EXCLUDES)]


def is_ignored(path):
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=REPO_ROOT,
    ).returncode == 0


class PublicHygieneTests(unittest.TestCase):
    def test_allowlist_and_rendered_files_are_not_tracked(self):
        files = set(tracked_files())
        for path in FORBIDDEN_TRACKED:
            self.assertNotIn(path, files)
        self.assertIn("infrastructure/browser-oauth-allowed-emails.txt.example", files)

    def test_no_secrets_directory_files_are_tracked(self):
        for path in tracked_files():
            if path.startswith("secrets/"):
                self.assertEqual(path, "secrets/.gitignore")

    def test_versions_env_is_not_ignored(self):
        self.assertFalse(
            is_ignored("versions.env"),
            "versions.env must survive the public export",
        )

    def test_start_requires_allowlist_from_secrets(self):
        text = (REPO_ROOT / "scripts" / "lib" / "allowlist.sh").read_text(encoding="utf-8")
        self.assertIn("secrets/browser-oauth-allowed-emails.txt", text)
        start = (REPO_ROOT / "scripts" / "start.sh").read_text(encoding="utf-8")
        self.assertIn("require_allowlist", start)

    def test_compose_enforces_the_allowlist_file(self):
        text = (REPO_ROOT / "docker-compose.platform.yml").read_text(encoding="utf-8")
        self.assertNotIn("--email-domain=*", text)
        self.assertIn("secrets/browser-oauth-allowed-emails.txt", text)
        self.assertIn("create_host_path: false", text)

    def test_traefik_healthcheck_requires_rendered_middleware(self):
        text = (REPO_ROOT / "docker-compose.platform.yml").read_text(encoding="utf-8")
        self.assertIn("/dynamic/middlewares.yml", text)

    def test_snapshot_has_no_placeholder_violations(self):
        forbidden = (
            "149." + "118.69.246",
            "192." + "168.1.25",
            "qacey" + ".com.au",
            "/home/" + "buhagiar",
            "@gmail" + ".com",
            "@hotmail" + ".com",
        )
        for path in snapshot_files():
            data = (REPO_ROOT / path).read_bytes()
            if b"\x00" in data:
                continue
            text = data.decode("utf-8", errors="ignore")
            for needle in forbidden:
                self.assertNotIn(needle, text, f"{path} contains a live value")


if __name__ == "__main__":
    unittest.main()
