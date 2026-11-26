import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DISPATCHER = REPO_ROOT / "scripts" / "deploy" / "homeserver-deploy"


class DispatcherTests(unittest.TestCase):
    def run_dispatcher(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log = tmp_path / "runuser.log"
            fake = tmp_path / "runuser"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f'echo "$@" >> "{log}"\n'
                "exit 0\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}
            result = subprocess.run(
                ["bash", str(DISPATCHER), *args],
                env=env,
                capture_output=True,
                text=True,
            )
            calls = log.read_text() if log.exists() else ""
            return result, calls

    def test_allowlisted_app_invokes_the_fixed_deploy_script(self):
        sha = "a" * 40
        result, calls = self.run_dispatcher("qacey-platform", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "-u buhagiar -- __PLATFORM_DIR__/scripts/deploy/auto-deploy.sh",
            calls,
        )
        self.assertIn(sha, calls)

    def test_unknown_app_is_refused(self):
        result, calls = self.run_dispatcher("unknown-app", "a" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "")

    def test_bad_sha_is_refused(self):
        result, calls = self.run_dispatcher("qacey-platform", "not-a-sha")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "")

    def test_new_app_slug_is_allowlisted(self):
        sha = "b" * 40
        result, calls = self.run_dispatcher("agentic-homelab", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("__PLATFORM_DIR__/scripts/deploy/auto-deploy.sh", calls)


if __name__ == "__main__":
    unittest.main()
