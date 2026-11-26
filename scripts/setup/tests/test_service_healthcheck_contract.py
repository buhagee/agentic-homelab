import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"


class ServiceHealthcheckContractTests(unittest.TestCase):
    def test_crawl4ai_checks_its_http_port(self):
        text = COMPOSE.read_text(encoding="utf-8")
        block = text.split("  crawl4ai:\n", 1)[1].split("  mcp-crawl4ai:\n", 1)[0]
        self.assertIn("healthcheck:", block)
        self.assertIn("('127.0.0.1', 11235)", block)

if __name__ == "__main__":
    unittest.main()
