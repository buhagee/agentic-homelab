import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
UNIT_DIR = REPO_ROOT / "infrastructure" / "renovate"
SERVICE = UNIT_DIR / "qacey-renovate.service"
TIMER = UNIT_DIR / "qacey-renovate.timer"
SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "trigger-renovate.sh"
INSTALLER = REPO_ROOT / "scripts" / "maintenance" / "install-renovate-timer.sh"


class RenovateTimerContractTests(unittest.TestCase):
    def test_timer_runs_daily_in_utc(self):
        text = TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 18:15:00 UTC", text)
        self.assertIn("Persistent=true", text)

    def test_service_runs_as_host_user(self):
        text = SERVICE.read_text(encoding="utf-8")
        self.assertIn("User=buhagiar", text)
        self.assertIn("scripts/maintenance/trigger-renovate.sh", text)

    def test_trigger_skips_recent_runs_and_dispatches(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("gh run list", text)
        self.assertIn("gh workflow run", text)
        self.assertIn("RENOVATE_RECENT_SECONDS", text)

    def test_installer_enables_timer(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("systemctl enable --now qacey-renovate.timer", text)

    def test_trigger_targets_the_public_repository(self):
        text = (REPO_ROOT / "scripts" / "maintenance" / "trigger-renovate.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("buhagee/agentic-homelab", text)


if __name__ == "__main__":
    unittest.main()
