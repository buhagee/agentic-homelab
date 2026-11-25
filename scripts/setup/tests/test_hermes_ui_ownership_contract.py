import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "operations" / "hermes-ui-ownership.md"
DEPLOY_README = REPO_ROOT / "scripts" / "deploy" / "README.md"
CONFIG = REPO_ROOT / "services" / "agent" / "config.shared.yaml"


class HermesUiOwnershipContractTests(unittest.TestCase):
    def test_contract_document_defines_the_writer_boundary(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("**UI owns:** MCP servers, plugins, skills, OAuth tokens", text)
        self.assertIn(
            "**Git owns:** base config seeds, images, networks, routes, personas, provider keys",
            text,
        )
        self.assertIn("**Deploy seeds. It never overwrites UI-owned state.**", text)
        self.assertIn("mcp_servers", text)
        self.assertIn("plugins", text)
        self.assertIn("reference only", text)
        self.assertIn("Back up", text)

    def test_deploy_readme_points_to_the_contract(self):
        text = DEPLOY_README.read_text(encoding="utf-8")
        self.assertIn("hermes-ui-ownership.md", text)
        self.assertIn("UI owns", text)
        self.assertIn("reference only", text)
        self.assertNotIn("Merges `config.shared.yaml` + per-user MCP JSON", text)

    def test_base_config_marks_seed_only_ownership(self):
        text = CONFIG.read_text(encoding="utf-8")
        self.assertIn("Git-owned config seed", text)
        self.assertIn("Hermes UI owns", text)
        self.assertIn("Deploy never overwrites", text)
        self.assertIn("mcp_servers", text)
        self.assertIn("plugins", text)


if __name__ == "__main__":
    unittest.main()
