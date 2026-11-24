import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class CiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = CI.read_text(encoding="utf-8")

    def test_workflow_runs_only_on_hosted_runners(self):
        self.assertIn("runs-on: ubuntu-latest", self.text)
        self.assertNotIn("self-hosted", self.text)

    def test_image_job_authenticates_to_ghcr(self):
        self.assertIn("packages: read", self.text)
        self.assertIn("docker/login-action@v3", self.text)
        self.assertIn("registry: ghcr.io", self.text)

    def test_scans_on_push_and_label_changes(self):
        self.assertIn("push:", self.text)
        self.assertIn("labeled", self.text)
        self.assertIn("unlabeled", self.text)

    def test_automerge_policy_uses_merge_base(self):
        self.assertIn("merge-base", self.text)

    def test_gitleaks_version_is_pinned(self):
        self.assertIn('GITLEAKS_VERSION: "8.30.1"', self.text)


if __name__ == "__main__":
    unittest.main()
