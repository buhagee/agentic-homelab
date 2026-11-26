import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
VERSIONS = REPO_ROOT / "versions.env"


class SearxngMcpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.versions = VERSIONS.read_text(encoding="utf-8")

    def test_image_is_versioned_and_immutable(self):
        image = re.search(r"^MCP_SEARXNG_IMAGE=(.+)$", self.versions, re.MULTILINE)
        self.assertIsNotNone(image)
        self.assertRegex(image.group(1), r"^isokoliuk/mcp-searxng:[^@\s]+@sha256:[0-9a-f]{64}$")
        self.assertNotIn(":latest", image.group(1))
        self.assertIn("image: ${MCP_SEARXNG_IMAGE}", self.compose)

    def test_service_is_internal_only_and_depends_on_healthy_searxng(self):
        service = self.compose.split("  mcp-searxng:\n", 1)[1].split(
            "\n  # ── U-03:", 1
        )[0]
        self.assertIn("condition: service_healthy", service)
        self.assertIn("- qacey-mcp-internal", service)
        self.assertNotIn("- qacey-internal", service)
        self.assertNotIn("qacey-proxy", service)
        self.assertNotIn("ports:", service)
        self.assertIn("MCP_HTTP_PORT: \"3000\"", service)
        self.assertIn("MCP_HTTP_HOST: 0.0.0.0", service)
        self.assertIn("SEARXNG_URL: http://searxng:8080", service)
        self.assertIn("http://127.0.0.1:3000/health", service)
        self.assertIn('traefik.enable=false', service)

    def test_mcp_network_is_shared_only_by_search_path_services(self):
        self.assertIn("qacey-mcp-internal:", self.compose)
        for service_name in ("searxng", "mcp-searxng"):
            service = self.compose.split(f"  {service_name}:\n", 1)[1].split(
                "\n  # ──", 1
            )[0]
            self.assertIn("qacey-mcp-internal", service)

        mcp_service = self.compose.split("  mcp-searxng:\n", 1)[1].split(
            "\n  # ──", 1
        )[0]
        self.assertNotIn("qacey-internal", mcp_service)

    def test_backend_json_format_remains(self):
        settings = (REPO_ROOT / "infrastructure/searxng/settings.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- html", settings)
        self.assertIn("- json", settings)

    def test_negative_guards_reject_public_or_stdio_shape(self):
        service = self.compose.split("  mcp-searxng:\n", 1)[1].split(
            "\n  # ── U-03:", 1
        )[0]
        self.assertNotRegex(service, r"(?m)^\s+ports:\s*$")
        self.assertNotIn('command: "uvx"', service)
        self.assertNotIn("MCP_SEARXNG_IMAGE=isokoliuk/mcp-searxng:latest", self.versions)


if __name__ == "__main__":
    unittest.main()