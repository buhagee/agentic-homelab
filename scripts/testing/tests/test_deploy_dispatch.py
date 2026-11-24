import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-dispatch.yml"


class DeployDispatchTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_runs_on_main_push(self):
        self.assertIn("push:", self.text)
        self.assertIn("branches: [main]", self.text)
        self.assertIn("workflow_dispatch:", self.text)
        self.assertNotIn("pull_request", self.text)

    def test_targets_homeserver_deploy_with_app_and_sha(self):
        self.assertIn("buhagee/homeserver-deploy/dispatches", self.text)
        self.assertIn("app: 'agentic-homelab'", self.text)
        self.assertIn("sha: context.sha", self.text)
        self.assertIn("event_type: 'deploy'", self.text)

    def test_skips_when_dispatch_token_is_missing(self):
        self.assertIn("DEPLOY_DISPATCH_TOKEN", self.text)
        self.assertIn(
            "if: github.ref == 'refs/heads/main' && env.DEPLOY_DISPATCH_TOKEN != ''",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
