import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller_logic import ControlError, compose_command, validate_request


class ControllerLogicTests(unittest.TestCase):
    def setUp(self):
        self.hashes = {"docker-compose.platform.yml": "approved"}
        self.manifest = {
            "services": ["opencode-v2", "homeassistant"],
            "deploy_services": ["opencode-v2"],
            "hashes": self.hashes,
        }

    def test_build_recreate_is_restricted_to_deployable_services(self):
        with self.assertRaisesRegex(ControlError, "host-level Docker capabilities"):
            validate_request("up", "homeassistant", self.manifest, self.hashes)

    def test_stale_compose_snapshot_blocks_operations(self):
        with self.assertRaisesRegex(ControlError, "changed after approval"):
            validate_request(
                "restart",
                "opencode-v2",
                self.manifest,
                {"docker-compose.platform.yml": "changed"},
            )

    def test_unknown_services_and_actions_are_rejected(self):
        with self.assertRaisesRegex(ControlError, "not on the approved list"):
            validate_request("stop", "new-service", self.manifest, self.hashes)
        with self.assertRaisesRegex(ControlError, "Unsupported action"):
            validate_request("exec", "opencode-v2", self.manifest, self.hashes)

    def test_up_is_fixed_to_one_service_without_dependencies(self):
        command = compose_command("up", "opencode-v2")
        self.assertEqual(command[-5:], ["up", "-d", "--no-deps", "--build", "opencode-v2"])


if __name__ == "__main__":
    unittest.main()
