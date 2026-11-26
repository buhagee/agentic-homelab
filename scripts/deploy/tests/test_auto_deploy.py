import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "auto-deploy.sh"


def run_git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class AutoDeployDryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.origin = root / "origin.git"
        self.home = root / "home"
        self.home.mkdir()
        self.repo.mkdir()
        subprocess.run(["git", "init", "--bare", str(self.origin)], check=True, capture_output=True)
        subprocess.run(["git", "init", "-b", "main", str(self.repo)], check=True, capture_output=True)
        run_git(self.repo, "config", "user.name", "Test")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / "README.md").write_text("initial\n")
        (self.repo / "versions.env").write_text(
            "TRAEFIK_VERSION=v3.7.14\n"
            "PAPERLESS_VERSION=3.3.0\n"
        )
        (self.repo / "docker-compose.platform.yml").write_text("services: {}\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "initial")
        run_git(self.repo, "remote", "add", "origin", str(self.origin))
        run_git(self.repo, "push", "-u", "origin", "main")
        self.base_sha = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, files, message):
        for name, content in files.items():
            (self.repo / name).write_text(content)
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", message)
        sha = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()
        run_git(self.repo, "push", "origin", "main")
        run_git(self.repo, "reset", "--hard", self.base_sha)
        return sha

    def run_script(self, *args):
        env = os.environ | {
            "HOME": str(self.home),
            "QACEY_DEPLOY_PLATFORM_DIR": str(self.repo),
        }
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_normal_commit_is_stateless(self):
        sha = self.commit({"README.md": "changed\n"}, "docs")
        result = self.run_script("--dry-run", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"target={sha}", result.stdout)
        self.assertIn("stateful=0", result.stdout)
        self.assertIn("already_deployed=0", result.stdout)

    def test_current_head_is_already_deployed(self):
        state = self.home / ".local" / "state" / "qacey-deploy"
        state.mkdir(parents=True)
        (state / "last-good").write_text(self.base_sha + "\n")
        result = self.run_script("--dry-run", self.base_sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already_deployed=1", result.stdout)

    def test_host_ahead_of_last_good_is_not_a_no_op(self):
        sha = self.commit({"README.md": "changed\n"}, "docs")
        run_git(self.repo, "reset", "--hard", sha)
        state = self.home / ".local" / "state" / "qacey-deploy"
        state.mkdir(parents=True)
        (state / "last-good").write_text(self.base_sha + "\n")
        result = self.run_script("--dry-run", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already_deployed=0", result.stdout)

    def test_stateful_version_change_is_detected(self):
        sha = self.commit(
            {"versions.env": "TRAEFIK_VERSION=v3.7.14\nPAPERLESS_VERSION=3.5.1\n"},
            "bump paperless",
        )
        result = self.run_script("--dry-run", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stateful=1", result.stdout)

    def test_compose_change_is_stateful(self):
        sha = self.commit(
            {"docker-compose.platform.yml": "services:\n  test: {}\n"},
            "compose change",
        )
        result = self.run_script("--dry-run", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stateful=1", result.stdout)

    def test_dirty_tracked_tree_is_refused(self):
        (self.repo / "README.md").write_text("dirty\n")
        result = self.run_script("--dry-run", "a" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked changes", result.stderr)

    def test_malformed_sha_is_refused(self):
        result = self.run_script("--dry-run", "not-a-sha")
        self.assertNotEqual(result.returncode, 0)

    def test_sha_not_on_main_is_refused(self):
        run_git(self.repo, "switch", "-c", "feature")
        (self.repo / "README.md").write_text("feature\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "feature")
        sha = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()
        run_git(self.repo, "switch", "main")
        run_git(self.repo, "reset", "--hard", self.base_sha)
        result = self.run_script("--dry-run", sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin/main", result.stderr)

    def test_older_main_commit_is_superseded(self):
        (self.repo / "README.md").write_text("first\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "first")
        first = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()
        run_git(self.repo, "push", "origin", "main")

        (self.repo / "README.md").write_text("second\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "second")
        run_git(self.repo, "push", "origin", "main")
        run_git(self.repo, "reset", "--hard", self.base_sha)

        result = self.run_script("--dry-run", first)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("superseded", result.stdout)

    def test_local_main_ahead_of_origin_is_refused(self):
        (self.repo / "README.md").write_text("local-only\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "local only")
        result = self.run_script("--dry-run", self.base_sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local main", result.stderr)

    def test_fresh_dump_gate_accepts_sqlite_and_two_hours(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('*.sqlite3.gz', text)
        self.assertIn("-newermt '-2 hours'", text)
        self.assertNotIn("-newermt '-15 minutes'", text)


if __name__ == "__main__":
    unittest.main()
