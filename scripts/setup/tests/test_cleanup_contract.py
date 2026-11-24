import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MAINTENANCE = REPO_ROOT / "scripts" / "maintenance"
SETUP_README = REPO_ROOT / "scripts" / "setup" / "README.md"
MAINT_README = MAINTENANCE / "README.md"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
VERSIONS = REPO_ROOT / "versions.env"


class CleanupContractTests(unittest.TestCase):
    def test_dead_maintenance_scripts_are_gone(self):
        for name in (
            "clear-memory-cache.sh",
            "manage-swap.sh",
            "install-monitoring.sh",
            "setup-memory-monitoring.sh",
            "memory-monitor-and-clean.sh",
        ):
            self.assertFalse((MAINTENANCE / name).exists(), name)

    def test_docs_no_longer_advertise_dead_installers(self):
        text = MAINT_README.read_text(encoding="utf-8")
        self.assertNotIn("install-monitoring.sh", text)
        self.assertIn("does **not** prune named volumes", text)

    def test_stale_environment_keys_are_gone(self):
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        for key in (
            "JELLYFIN_USER",
            "JELLYFIN_PASSWORD",
            "IMMICH_MUM_API_KEY",
            "TEMPO_HOST_PORT",
            "OTLP_GRPC_HOST_PORT",
            "OTLP_HTTP_HOST_PORT",
        ):
            self.assertNotIn(key, text)

    def test_unused_version_pin_is_gone(self):
        self.assertNotIn("CS_BOUNCER_PLUGIN_VERSION", VERSIONS.read_text(encoding="utf-8"))

    def test_hacs_util_is_documented(self):
        self.assertIn("install-hacs.sh", SETUP_README.read_text(encoding="utf-8"))

    def test_nextcloud_is_removed(self):
        compose = (REPO_ROOT / "docker-compose.platform.yml").read_text(encoding="utf-8")
        self.assertNotIn("nextcloud", compose.lower())
        self.assertFalse((REPO_ROOT / "infrastructure" / "nextcloud").exists())
        self.assertFalse((REPO_ROOT / "scripts" / "setup" / "configure-nextcloud.sh").exists())
        self.assertNotIn("NEXTCLOUD_", ENV_EXAMPLE.read_text(encoding="utf-8"))
        health = (REPO_ROOT / "scripts" / "maintenance" / "platform-healthcheck.sh").read_text(encoding="utf-8")
        self.assertNotIn("nextcloud", health.lower())

    def test_rtk_is_removed_from_hermes(self):
        self.assertFalse((REPO_ROOT / "services" / "agent" / "task.Dockerfile").exists())
        for relative in (
            "services/agent/Dockerfile",
            "services/agent/config.shared.yaml",
            "scripts/build.sh",
            "scripts/deploy/README.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertNotIn("rtk", text, relative)

    def test_no_tracked_pycache(self):
        if not (REPO_ROOT / ".git").exists():
            self.skipTest("no git metadata")
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertNotIn("__pycache__", result.stdout)

    def test_env_example_lines_are_parseable(self):
        for lineno, line in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.assertRegex(
                line,
                r"^[A-Za-z_][A-Za-z0-9_]*=",
                f".env.example:{lineno} is not KEY=VALUE: {line!r}",
            )

    def test_no_runtime_plugin_installs_into_hermes_venv(self):
        deploy = (REPO_ROOT / "scripts" / "deploy" / "deploy-agent-config.sh").read_text(encoding="utf-8")
        self.assertNotIn("hermes-curator-evolver", deploy)
        self.assertNotIn("uv pip install", deploy.split("Hermes plugins", 1)[-1])


if __name__ == "__main__":
    unittest.main()
