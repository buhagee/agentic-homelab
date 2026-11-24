import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "testing" / "build-changed-images.sh"


class BuildChangedImagesTests(unittest.TestCase):
    def run_script(self, changed_files):
        compose = {
            "services": {
                "svc-a": {"build": {"context": str(REPO_ROOT / "services" / "a")}},
                "svc-b": {"build": {"context": str(REPO_ROOT / "services" / "b")}},
                "remote": {"image": "traefik:v3.7.1"},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "docker"
            log = tmp_path / "docker.log"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f'echo "$@" >> "{log}"\n'
                "exit 0\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            changed = tmp_path / "changed.txt"
            changed.write_text("\n".join(changed_files) + "\n")
            compose_file = tmp_path / "compose.json"
            compose_file.write_text(json.dumps(compose))
            env = os.environ | {
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "QACEY_CHANGED_FILES": str(changed),
                "QACEY_COMPOSE_JSON": str(compose_file),
            }
            result = subprocess.run(
                ["bash", str(SCRIPT), "base", "head"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            calls = log.read_text() if log.exists() else ""
            return result, calls

    def test_builds_only_the_service_whose_context_changed(self):
        result, calls = self.run_script(["services/a/file.py"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build svc-a", calls)
        self.assertNotIn("build svc-b", calls)
        self.assertNotIn("traefik", calls)

    def test_skips_when_no_local_context_changed(self):
        result, calls = self.run_script(["README.md"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no local images changed", result.stdout)
        self.assertEqual(calls, "")

    def test_ignores_pycache_changes(self):
        result, calls = self.run_script(["services/a/__pycache__/module.pyc"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no local images changed", result.stdout)
        self.assertEqual(calls, "")

    def test_compose_config_includes_profiles(self):
        compose = {
            "services": {
                "svc-a": {"build": {"context": str(REPO_ROOT / "services" / "a")}},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "docker"
            log = tmp_path / "docker.log"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f'echo "$@" >> "{log}"\n'
                'if [[ "$1" == "compose" ]]; then\n'
                f"  cat <<'JSON'\n{json.dumps(compose)}\nJSON\n"
                "  exit 0\n"
                "fi\n"
                "exit 0\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            git = tmp_path / "git"
            git.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "$1" == "diff" ]]; then echo "services/a/file.py"; exit 0; fi\n'
                "exit 1\n"
            )
            git.chmod(git.stat().st_mode | stat.S_IEXEC)
            changed = tmp_path / "changed.txt"
            changed.write_text("services/a/file.py\n")
            env = os.environ | {
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
            }
            env.pop("QACEY_CHANGED_FILES", None)
            env.pop("QACEY_COMPOSE_JSON", None)
            result = subprocess.run(
                ["bash", str(SCRIPT), "base", "head"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--profile *", log.read_text())

    def test_fails_when_compose_config_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "docker"
            fake.write_text("#!/usr/bin/env bash\nexit 1\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            changed = tmp_path / "changed.txt"
            changed.write_text("services/a/file.py\n")
            env = os.environ | {
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "QACEY_CHANGED_FILES": str(changed),
            }
            env.pop("QACEY_COMPOSE_JSON", None)
            result = subprocess.run(
                ["bash", str(SCRIPT), "base", "head"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
