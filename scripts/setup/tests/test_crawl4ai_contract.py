import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
SERVER = REPO_ROOT / "services" / "mcp" / "crawl4ai" / "server.py"
FIRST_TIME_SETUP = REPO_ROOT / "scripts" / "setup" / "first-time-setup.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


class Crawl4AIContractTests(unittest.TestCase):
    def test_bridge_sends_bearer_token(self):
        text = SERVER.read_text(encoding="utf-8")
        self.assertIn("CRAWL4AI_API_TOKEN", text)
        self.assertIn("Authorization", text)
        self.assertIn("Bearer", text)

    def test_both_services_receive_the_token(self):
        text = COMPOSE.read_text(encoding="utf-8")
        crawl_block = text.split("  crawl4ai:\n", 1)[1].split("  mcp-crawl4ai:\n", 1)[0]
        mcp_block = text.split("  mcp-crawl4ai:\n", 1)[1].split("  mcp-academic-papers:\n", 1)[0]
        for block in (crawl_block, mcp_block):
            self.assertIn("CRAWL4AI_API_TOKEN", block)
            self.assertIn("${CRAWL4AI_API_TOKEN}", block)

    def test_first_time_setup_generates_the_token(self):
        text = FIRST_TIME_SETUP.read_text(encoding="utf-8")
        self.assertIn("CRAWL4AI_API_TOKEN", text)
        self.assertIn("CRAWL4AI_API_TOKEN=${CRAWL4AI_API_TOKEN}", text)

    def test_env_example_documents_the_secret(self):
        self.assertIn("CRAWL4AI_API_TOKEN", ENV_EXAMPLE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
