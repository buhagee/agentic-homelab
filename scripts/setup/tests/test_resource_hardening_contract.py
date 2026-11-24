import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"


def service_block(text, name):
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_.-]+:\s*$|\Z)",
        text,
        re.M | re.S,
    )
    if not match:
        raise AssertionError(f"missing service: {name}")
    return match.group(1)


class ResourceHardeningContractTests(unittest.TestCase):
    def setUp(self):
        self.text = COMPOSE.read_text(encoding="utf-8")

    def test_unlimited_services_now_have_limits(self):
        self.assertIn("memory: 8g", service_block(self.text, "ollama"))
        self.assertIn("memory: 512m", service_block(self.text, "hermes-webui-annique"))
        self.assertIn("mem_limit: 256m", service_block(self.text, "hermes-sandbox-oauth2-proxy"))

    def test_core_services_have_healthchecks(self):
        for name in (
            "opencode-v2",
            "opencode-docker-control",
            "traefik",
            "crowdsec",
            "skillclaw",
            "mnemo-postgres",
            "mcp-paperless",
            "mcp-crawl4ai",
            "mcp-academic-papers",
            "mcp-intervals",
        ):
            self.assertIn("healthcheck:", service_block(self.text, name), name)

    def test_application_and_data_services_drop_new_privileges(self):
        for name in (
            "ollama",
            "cloudflared",
            "paperless",
            "paperless-postgres",
            "paperless-redis",
            "mcp-paperless",
            "immich-machine-learning",
            "immich-redis",
            "immich-postgres",
        ):
            self.assertIn("no-new-privileges:true", service_block(self.text, name), name)

    def test_traefik_8080_is_loopback_only(self):
        block = service_block(self.text, "traefik")
        self.assertIn('"127.0.0.1:8080:8080"', block)
        self.assertNotIn('"8080:8080"', block)


if __name__ == "__main__":
    unittest.main()
