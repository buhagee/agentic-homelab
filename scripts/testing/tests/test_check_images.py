import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "testing" / "check-images.sh"


class CheckImagesTests(unittest.TestCase):
    def run_script(self, images, manifest_rc=0):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "docker"
            log = tmp_path / "docker.log"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f'echo "$@" >> "{log}"\n'
                f"exit {manifest_rc}\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            image_file = tmp_path / "images.txt"
            image_file.write_text(images)
            env = os.environ | {
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "QACEY_IMAGES_OVERRIDE": str(image_file),
                "CHECK_IMAGES_RETRY_DELAY": "0",
            }
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            calls = log.read_text() if log.exists() else ""
            return result, calls

    def test_passes_for_tagged_image_and_skips_local(self):
        result, calls = self.run_script(
            "traefik:v3.7.1\nqacey/mcp-test:local\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("manifest inspect traefik:v3.7.1", calls)
        self.assertNotIn("qacey/mcp-test:local", calls)

    def test_rejects_latest(self):
        result, _ = self.run_script("traefik:latest\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("latest", result.stderr)

    def test_rejects_untagged(self):
        result, _ = self.run_script("traefik\n")
        self.assertNotEqual(result.returncode, 0)

    def test_fails_when_manifest_lookup_fails(self):
        result, _ = self.run_script("traefik:v3.7.1\n", manifest_rc=1)
        self.assertNotEqual(result.returncode, 0)

    def test_deduplicates_repeated_images(self):
        result, calls = self.run_script("redis:8-alpine\nredis:8-alpine\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.count("manifest inspect redis:8-alpine"), 1)

    def test_rejects_latest_even_with_digest(self):
        result, _ = self.run_script("traefik:latest@sha256:abc\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("latest", result.stderr)

    def test_rejects_empty_tag(self):
        result, _ = self.run_script("traefik:\n")
        self.assertNotEqual(result.returncode, 0)

    def test_digest_reference_is_inspected_without_tag(self):
        digest = "sha256:" + "a" * 64
        result, calls = self.run_script(
            f"isokoliuk/mcp-searxng:2.5.1@{digest}\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"manifest inspect isokoliuk/mcp-searxng@{digest}",
            calls,
        )
        self.assertNotIn(f":2.5.1@{digest}", calls)

    def test_fails_when_no_images_are_present(self):
        result, _ = self.run_script("")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no images", result.stderr)

    def test_compose_config_includes_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "docker"
            log = tmp_path / "docker.log"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f'echo "$@" >> "{log}"\n'
                'if [[ "$1" == "compose" ]]; then\n'
                '  echo "traefik:v3.7.1"\n'
                "  exit 0\n"
                "fi\n"
                "exit 0\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            env = os.environ | {
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "CHECK_IMAGES_RETRY_DELAY": "0",
            }
            env.pop("QACEY_IMAGES_OVERRIDE", None)
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--profile *", log.read_text())


if __name__ == "__main__":
    unittest.main()
