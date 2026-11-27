"""Exercise the real platform shell flow with disposable Git and command fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class NativeDeployHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.origin = self.root / "origin.git"
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.helper = self.root / "qacey-dev-deploy"
        self.calls = self.root / "calls"
        self.log = self.root / "deploy.log"
        self.backups = self.root / "backups"
        for path in (self.repo, self.home, self.bin, self.backups):
            path.mkdir()
        self.env = os.environ | {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "QACEY_DEPLOY_PLATFORM_DIR": str(self.repo),
            "QACEY_DEPLOY_LOG": str(self.log),
            "QACEY_DEPLOY_LOCK": str(self.root / "deploy.lock"),
            "TEST_CALLS": str(self.calls),
            "HEALTH_RESULT": "0",
            "NATIVE_RESULT": "0",
        }
        subprocess.run(["git", "init", "--bare", str(self.origin)],
                       check=True, capture_output=True)
        subprocess.run(["git", "init", "-b", "main", str(self.repo)],
                       check=True, capture_output=True)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        for name in ("auto-deploy.sh", "reconcile.sh"):
            content = (ROOT / "scripts/deploy" / name).read_text()
            content = content.replace("/usr/local/sbin/qacey-dev-deploy", str(self.helper))
            content = content.replace("/mnt/hdd1/qacey/db-backups", str(self.backups))
            self.write(self.repo / "scripts/deploy" / name, content)
        self.write(self.repo / "scripts/lib/alert.sh",
                   'send_alert() { printf "alert:%s\\n" "$1" >> "$TEST_CALLS"; }\n'
                   'observe_incident() { printf "incident:%s:%s\\n" "$1" "$2" >> "$TEST_CALLS"; }\n')
        self.write(self.repo / "scripts/lib/platform-env.sh",
                   "load_platform_env() { return 0; }\n")
        self.write(self.repo / "scripts/lib/render-config.sh",
                   "render_traefik_dynamic() { return 0; }\n")
        self.write(self.repo / "scripts/testing/build-changed-images.sh",
                   'printf "build\\n" >> "$TEST_CALLS"\n')
        self.write(self.repo / "scripts/maintenance/platform-healthcheck.sh",
                   'printf "health\\n" >> "$TEST_CALLS"\nexit "$HEALTH_RESULT"\n')
        self.write(self.repo / "README.md", "initial\n")
        self.write(self.repo / "versions.env", "TRAEFIK_VERSION=v3.8.0\n")
        self.write(self.repo / "docker-compose.platform.yml", "services: {}\n")
        self.write(self.bin / "sudo", """#!/bin/bash
printf 'sudo:%s\\n' "$*" >> "$TEST_CALLS"
test "$1" = -n || exit 98
shift
if test "$1" = systemctl; then exit 0; fi
exec "$@"
""", executable=True)
        self.write(self.bin / "docker", """#!/bin/bash
printf 'docker:%s\\n' "$*" >> "$TEST_CALLS"
if test "$1" = ps; then
    test "$2" = -aq || exit 97
    test "$3" = --filter && test "$4" = label=com.docker.compose.project=qacey-platform || exit 97
    test "$5" = --filter && test "$#" = 6 || exit 97
    if test "${RETIRED_FIXTURE:-0}" = 1; then
        case "$6" in
            label=com.docker.compose.service=skillclaw) echo aaa111 ;;
            label=com.docker.compose.service=hermes-justin) echo bbb222 ;;
            label=com.docker.compose.service=opencode-docker-control) echo ccc333 ;;
            label=com.docker.compose.service=mnemo-postgres) echo ddd444 ;;
        esac
    fi
    exit 0
fi
if test "$1" = rm; then exit 0; fi
if test "$1" = compose; then exit 0; fi
exit 97
""", executable=True)
        self.write(self.helper, """#!/bin/bash
test "$#" = 2 && test "$1" = apply || exit 96
test "$(cat "$HOME/.local/state/qacey-deploy/last-good")" = "$2" || exit 95
printf 'native:%s\\n' "$2" >> "$TEST_CALLS"
exit "$NATIVE_RESULT"
""", executable=True)
        for prefix in ("immich", "paperless"):
            (self.backups / f"{prefix}_fixture.sql.gz").write_bytes(b"x" * 200)
        self.git("add", "-A")
        self.git("commit", "-m", "fixture")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-u", "origin", "main")
        self.base = self.git("rev-parse", "HEAD")
        self.state = self.home / ".local/state/qacey-deploy"
        self.state.mkdir(parents=True)
        (self.state / "last-good").write_text(self.base + "\n")

    @staticmethod
    def write(path, value, executable=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        if executable:
            path.chmod(0o755)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def new_target(self):
        (self.repo / "README.md").write_text("next\n")
        self.git("add", "README.md")
        self.git("commit", "-m", "next")
        target = self.git("rev-parse", "HEAD")
        self.git("push", "origin", "main")
        self.git("reset", "--hard", self.base)
        return target

    def run_deploy(self, target):
        return subprocess.run(["bash", str(self.repo / "scripts/deploy/auto-deploy.sh"), target],
                              env=self.env, capture_output=True, text=True, timeout=20)

    def events(self):
        return self.calls.read_text() if self.calls.exists() else ""

    def test_native_failure_does_not_rollback_successful_platform(self):
        target = self.new_target()
        self.env["NATIVE_RESULT"] = "73"
        result = self.run_deploy(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), target)
        self.assertEqual((self.state / "last-good").read_text().strip(), target)
        self.assertFalse((self.state / "failed-sha").exists())
        events = self.events()
        self.assertLess(events.index("health"), events.index("native:"))
        self.assertEqual(events.count("native:"), 1)
        self.assertEqual(events.count("build\n"), 1)
        self.assertIn("incident:native-deploy:failed", events)
        self.assertNotIn("rolling back", self.log.read_text())

    def test_platform_deploy_removes_only_retired_project_containers(self):
        self.env["RETIRED_FIXTURE"] = "1"
        result = self.run_deploy(self.new_target())
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self.events().splitlines()
        removes = [line for line in events if line.startswith("docker:rm ")]
        self.assertEqual(removes, ["docker:rm -f aaa111", "docker:rm -f ccc333", "docker:rm -f bbb222",
                                   "docker:rm -f ddd444"])
        self.assertLess(events.index("health"), events.index(removes[0]))
        self.assertTrue(any(line.startswith("native:") for line in events))

    def test_failed_platform_and_rollback_never_invoke_native_updater(self):
        target = self.new_target()
        self.env["HEALTH_RESULT"] = "1"
        result = self.run_deploy(target)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("native:", self.events())
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertEqual((self.state / "last-good").read_text().strip(), self.base)
        self.assertEqual((self.state / "failed-sha").read_text().strip(), target)

    def test_native_deferral_retries_when_platform_already_deployed(self):
        for _ in range(2):
            result = subprocess.run(["bash", str(self.repo / "scripts/deploy/reconcile.sh")],
                                    env=self.env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events().count("native:" + self.base), 2)
        self.assertNotIn("build\n", self.events())
        self.assertNotIn("systemctl", self.events())

    def test_unbootstrapped_current_platform_remains_noop(self):
        self.helper.unlink()
        result = subprocess.run(["bash", str(self.repo / "scripts/deploy/reconcile.sh")],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events(), "")

    def test_unbootstrapped_new_platform_succeeds_without_native_call(self):
        self.helper.unlink()
        target = self.new_target()
        result = self.run_deploy(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / "last-good").read_text().strip(), target)
        self.assertNotIn("native:", self.events())

    def test_native_failure_on_unchanged_platform_remains_retryable(self):
        self.env["NATIVE_RESULT"] = "73"
        result = self.run_deploy(self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.state / "failed-sha").exists())
        self.env["NATIVE_RESULT"] = "0"
        result = self.run_deploy(self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events().count("native:"), 2)

    def test_failed_revision_retries_its_notification_without_redeploy(self):
        target = self.new_target()
        (self.state / "failed-sha").write_text(target + "\n")
        result = subprocess.run(["bash", str(self.repo / "scripts/deploy/reconcile.sh")],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events().splitlines(), ["incident:platform-deploy:failed"])


if __name__ == "__main__":
    unittest.main()
