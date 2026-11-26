import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "testing" / "check-secrets.sh"


class CheckSecretsScriptTests(unittest.TestCase):
    def make_root(self, with_git=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        root.mkdir()
        (root / "README.md").write_text("hello\n", encoding="utf-8")
        if with_git:
            subprocess.run(["git", "init", "-q", str(root)], check=True)
        return root, Path(tmp.name)

    def run_script(self, root, bindir, env_extra=None):
        bindir.mkdir(exist_ok=True)
        log = bindir / "gitleaks.log"
        fake = bindir / "gitleaks"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$@" >> "{log}"\n'
            "exit 0\n"
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env = os.environ | {"PATH": f"{bindir}:{os.environ['PATH']}"}
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            ["bash", str(SCRIPT), str(root)],
            env=env, capture_output=True, text=True,
        )
        calls = log.read_text() if log.exists() else ""
        return result, calls

    def test_uses_directory_mode_outside_git(self):
        root, tmp = self.make_root()
        result, calls = self.run_script(root, tmp / "bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dir", calls)

    def test_uses_git_mode_inside_git(self):
        root, tmp = self.make_root(with_git=True)
        result, calls = self.run_script(root, tmp / "bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("git", calls)

    def test_requires_gitleaks_when_asked(self):
        root, tmp = self.make_root()
        empty_bin = tmp / "empty"
        empty_bin.mkdir()
        env = os.environ | {
            "PATH": f"{empty_bin}:/usr/bin:/bin",
            "REQUIRE_GITLEAKS": "1",
        }
        result = subprocess.run(
            ["bash", str(SCRIPT), str(root)],
            env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
