import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY = REPO_ROOT / "scripts" / "deploy" / "deploy-agent-config.sh"
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
CONFIG = REPO_ROOT / "services" / "agent" / "config.shared.yaml"
ARCHIVE = REPO_ROOT / "docs" / "operations" / "hermes-mcp-reference"
AGENT_DIR = REPO_ROOT / "services" / "agent"
DOC = REPO_ROOT / "docs" / "operations" / "hermes-ui-ownership.md"


def compose_block(name):
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"  {name}:\n", 1)[1].split("\n  # ──", 1)[0]


class HermesSeedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deploy = DEPLOY.read_text(encoding="utf-8")

    def test_deploy_seeds_config_env_and_soul_only_when_missing(self):
        self.assertIn("seed_config_yaml()", self.deploy)
        self.assertIn("seed_runtime_env()", self.deploy)
        self.assertIn("seed_soul()", self.deploy)
        self.assertIn("config.yaml exists; leaving UI-owned config unchanged", self.deploy)
        self.assertIn(".env exists; leaving UI-owned env unchanged", self.deploy)
        self.assertIn("SOUL.md exists; leaving UI-owned persona unchanged", self.deploy)
        self.assertNotIn("hermes_state_merge", self.deploy)
        self.assertNotIn("pre-deploy", self.deploy)
        self.assertNotIn("config.yaml.pre-deploy", self.deploy)

    def test_deploy_does_not_merge_live_ui_blocks(self):
        self.assertNotIn("write_config_yaml", self.deploy)
        self.assertNotIn("write_runtime_env", self.deploy)
        self.assertNotIn("--managed-key", self.deploy)
        self.assertNotIn("mcp-servers.shared.json", self.deploy)

    def test_compose_no_longer_passes_provider_keys(self):
        for service in ("hermes-justin", "hermes-annique"):
            block = compose_block(service)
            for key in (
                "OPENCODE_GO_API_KEY",
                "OPENCODE_GO_BASE_URL",
                "OPENROUTER_API_KEY",
                "OPENAI_API_KEY",
            ):
                self.assertNotIn(f"{key}:", block, f"{service} still passes {key}")

    def test_mcp_manifests_are_archived(self):
        for name in (
            "mcp-servers.shared.json",
            "mcp-servers.justin.json",
            "mcp-servers.annique.json",
        ):
            self.assertTrue((ARCHIVE / name).is_file(), name)
            self.assertFalse((AGENT_DIR / name).exists(), name)
        readme = (ARCHIVE / "README.md").read_text(encoding="utf-8")
        self.assertIn("reference only", readme)
        self.assertIn("Hermes UI", readme)

    def test_config_seed_is_marked_as_seed_only(self):
        text = CONFIG.read_text(encoding="utf-8")
        self.assertIn("seed", text.lower())
        self.assertIn("only when", text.lower())
        self.assertIn("missing", text.lower())

    def test_docs_describe_seed_only_behavior(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("seed", text.lower())
        self.assertIn("only when", text.lower())
        self.assertIn("hermes-mcp-reference", text)


if __name__ == "__main__":
    unittest.main()
