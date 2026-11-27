import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "testing"))
from check_automerge_policy import evaluate


class AutomergePolicyTests(unittest.TestCase):
    def test_renovate_stateless_versions_only_passes(self):
        self.assertIsNone(
            evaluate("renovate[bot]", ["stateless"], ["versions.env"])
        )

    def test_renovate_manual_update_passes(self):
        self.assertIsNone(evaluate("renovate[bot]", [], ["versions.env"]))

    def test_renovate_touching_compose_fails(self):
        self.assertIsNotNone(
            evaluate(
                "renovate[bot]",
                ["stateless"],
                ["versions.env", "docker-compose.platform.yml"],
            )
        )

    def test_renovate_stateful_touching_compose_fails(self):
        self.assertIsNotNone(
            evaluate(
                "renovate[bot]",
                ["stateful"],
                ["versions.env", "docker-compose.platform.yml"],
            )
        )

    def test_human_author_is_not_constrained(self):
        self.assertIsNone(
            evaluate("alice", [], ["docker-compose.platform.yml"])
        )

    def test_renovate_native_runtime_patch_or_minor_passes(self):
        self.assertIsNone(
            evaluate(
                "qacey-renovate[bot]",
                ["native-runtime"],
                [
                    "infrastructure/dev-agent/release.json",
                    "infrastructure/dev-agent/runtime/openchamber/package.json",
                    "infrastructure/dev-agent/runtime/openchamber/package-lock.json",
                ],
            )
        )

    def test_renovate_native_runtime_release_only_passes(self):
        self.assertIsNone(
            evaluate(
                "qacey-renovate[bot]",
                ["native-runtime"],
                ["infrastructure/dev-agent/release.json"],
            )
        )

    def test_renovate_native_runtime_major_fails(self):
        reason = evaluate(
            "qacey-renovate[bot]",
            ["native-runtime", "major"],
            ["infrastructure/dev-agent/release.json"],
        )
        self.assertIsNotNone(reason)
        self.assertIn("major", reason.lower())

    def test_renovate_mixing_versions_and_native_runtime_fails(self):
        self.assertIsNotNone(
            evaluate(
                "qacey-renovate[bot]",
                ["native-runtime"],
                ["versions.env", "infrastructure/dev-agent/release.json"],
            )
        )


if __name__ == "__main__":
    unittest.main()
