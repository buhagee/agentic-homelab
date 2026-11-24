import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RULESET = REPO_ROOT / "scripts" / "setup" / "github-main-ruleset.json"
REQUIRED_CHECKS = {
    "tests",
    "compose-config",
    "images",
    "renovate-config",
    "secrets",
    "automerge-policy",
    "opencode-smoke",
}


class GithubRulesetTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(RULESET.read_text(encoding="utf-8"))

    def test_ruleset_is_active_on_the_default_branch(self):
        self.assertEqual(self.data["target"], "branch")
        self.assertEqual(self.data["enforcement"], "active")
        self.assertEqual(self.data["conditions"]["ref_name"]["include"], ["~DEFAULT_BRANCH"])

    def test_nobody_bypasses_the_ruleset(self):
        self.assertEqual(self.data["bypass_actors"], [])

    def test_pull_request_is_required_without_approvals(self):
        rule = next(r for r in self.data["rules"] if r["type"] == "pull_request")
        params = rule["parameters"]
        self.assertEqual(params["required_approving_review_count"], 0)
        self.assertTrue(params["required_review_thread_resolution"])

    def test_direct_pushes_and_deletion_are_blocked(self):
        types = {rule["type"] for rule in self.data["rules"]}
        self.assertIn("non_fast_forward", types)
        self.assertIn("deletion", types)

    def test_all_pipeline_checks_are_required(self):
        rule = next(r for r in self.data["rules"] if r["type"] == "required_status_checks")
        contexts = {c["context"] for c in rule["parameters"]["required_status_checks"]}
        self.assertEqual(contexts, REQUIRED_CHECKS)
        self.assertTrue(rule["parameters"]["strict_required_status_checks_policy"])


if __name__ == "__main__":
    unittest.main()
