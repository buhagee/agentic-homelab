import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
AGENT = REPO_ROOT / "services" / "agent"
CRONTAB = REPO_ROOT / "scripts" / "crontab.txt"
DEPLOY = REPO_ROOT / "scripts" / "deploy" / "deploy-agent-config.sh"
RETIRE = REPO_ROOT / "scripts" / "maintenance" / "retire-hermes-monitoring.sh"


def compose_block(name):
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_.-]+:\s*$|\Z)",
        text,
        re.M | re.S,
    )
    if not match:
        raise AssertionError(f"compose service not found: {name}")
    return match.group(1)


class HermesAccessContractTests(unittest.TestCase):
    def test_hermes_justin_has_no_host_mount_or_group(self):
        block = compose_block("hermes-justin")
        self.assertNotIn("/:/host:ro", block)
        self.assertNotIn("group_add:", block)

    def test_hermes_monitoring_scripts_are_gone(self):
        self.assertFalse((AGENT / "scripts/platform-monitor.sh").exists())
        self.assertFalse((AGENT / "scripts/nightly-digest.sh").exists())

    def test_crontab_and_deploy_no_longer_mention_monitoring(self):
        self.assertNotIn("platform-monitor", CRONTAB.read_text(encoding="utf-8"))
        self.assertNotIn("nightly-digest", CRONTAB.read_text(encoding="utf-8"))
        text = DEPLOY.read_text(encoding="utf-8")
        self.assertNotIn("hermes cron create", text)
        self.assertNotIn("--script platform-monitor.sh", text)
        self.assertIn('run_privileged rm -f "$JUSTIN_SCRIPTS_DIR/platform-monitor.sh"', text)

    def test_persona_no_longer_advertises_host_mount(self):
        self.assertNotIn("/host", (AGENT / "persona.justin.md").read_text(encoding="utf-8"))

    def test_retirement_script_names_both_jobs(self):
        text = RETIRE.read_text(encoding="utf-8")
        self.assertIn("platform-monitor", text)
        self.assertIn("nightly-digest", text)
        self.assertIn("hermes cron delete", text)


if __name__ == "__main__":
    unittest.main()
