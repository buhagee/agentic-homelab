import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FIRST_TIME_SETUP = REPO_ROOT / "scripts" / "setup" / "first-time-setup.sh"
INSTALL_BACKUP = REPO_ROOT / "scripts" / "maintenance" / "install-backup.sh"
SERVER_SETUP = REPO_ROOT / "scripts" / "setup" / "server-setup-home.sh"


class BootstrapContractTests(unittest.TestCase):
    def test_first_time_setup_targets_repo_root_and_runtime_paths(self) -> None:
        script = FIRST_TIME_SETUP.read_text(encoding="utf-8")

        self.assertIn('PLATFORM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"', script)
        self.assertNotIn('HERMES_BASE_DIR', script)

    def test_first_time_setup_calls_platform_start_without_legacy_agent_setup(self) -> None:
        script = FIRST_TIME_SETUP.read_text(encoding="utf-8")

        self.assertNotIn('deploy-agent-config.sh', script)
        self.assertIn('START_SCRIPT="${PLATFORM_DIR}/scripts/start.sh"', script)

    def test_install_backup_resolves_repo_root_and_units_from_repo(self) -> None:
        script = INSTALL_BACKUP.read_text(encoding="utf-8")

        self.assertIn('PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"', script)
        self.assertIn('BACKUP_UNIT_DIR="${PLATFORM_DIR}/infrastructure/backup"', script)
        for unit_name in (
            "qacey-db-backup.service",
            "qacey-backup.service",
            "qacey-backup.timer",
        ):
            self.assertTrue(
                (REPO_ROOT / "infrastructure" / "backup" / unit_name).is_file(),
                f"missing backup unit fixture: {unit_name}",
            )

    def test_adguard_web_ui_is_reachable_from_docker_networks(self) -> None:
        script = SERVER_SETUP.read_text(encoding="utf-8")
        self.assertIn(
            "ufw allow from 172.16.0.0/12 to any port 3000 proto tcp", script
        )


if __name__ == "__main__":
    unittest.main()