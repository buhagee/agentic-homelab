import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY = REPO_ROOT / "infrastructure" / "deploy"
SERVICE = DEPLOY / "qacey-deploy-reconcile.service"
TIMER = DEPLOY / "qacey-deploy-reconcile.timer"
RECONCILE = REPO_ROOT / "scripts" / "deploy" / "reconcile.sh"
INSTALLER = REPO_ROOT / "scripts" / "deploy" / "install-reconcile-timer.sh"


class ReconcileTimerContractTests(unittest.TestCase):
    def test_timer_runs_every_ten_minutes(self):
        text = TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*:0/10", text)
        self.assertIn("Persistent=true", text)

    def test_service_runs_reconcile_as_host_user(self):
        text = SERVICE.read_text(encoding="utf-8")
        self.assertIn("User=buhagiar", text)
        self.assertIn("scripts/deploy/reconcile.sh", text)

    def test_reconcile_checks_last_good_and_failed_sha(self):
        text = RECONCILE.read_text(encoding="utf-8")
        self.assertIn("origin/main", text)
        self.assertIn("last-good", text)
        self.assertIn("failed-sha", text)
        self.assertIn("auto-deploy.sh", text)

    def test_installer_enables_timer(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("systemctl enable --now qacey-deploy-reconcile.timer", text)


if __name__ == "__main__":
    unittest.main()
