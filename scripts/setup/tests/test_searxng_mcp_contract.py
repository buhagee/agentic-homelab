import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "docs" / "operations" / "hermes-mcp-reference" / "mcp-servers.shared.json"
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
VERSIONS = REPO_ROOT / "versions.env"
DEPLOY = REPO_ROOT / "scripts" / "deploy" / "deploy-agent-config.sh"


class SearxngMcpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.versions = VERSIONS.read_text(encoding="utf-8")
        cls.deploy = DEPLOY.read_text(encoding="utf-8")

    def test_shared_manifest_uses_internal_streamable_http_alias(self):
        entry = self.manifest["mcp_searxng"]
        self.assertEqual(entry, {
            "url": "http://mcp-searxng:3000/mcp",
            "transport": "streamable_http",
        })
        self.assertNotIn("command", entry)
        self.assertNotIn("uvx", json.dumps(entry))
        self.assertNotIn("mcp-searxng==", json.dumps(entry))

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
        for service_name in ("searxng", "hermes-justin", "hermes-annique", "mcp-searxng"):
            service = self.compose.split(f"  {service_name}:\n", 1)[1].split(
                "\n  # ──", 1
            )[0]
            self.assertIn("qacey-mcp-internal", service)

        mcp_service = self.compose.split("  mcp-searxng:\n", 1)[1].split(
            "\n  # ──", 1
        )[0]
        self.assertNotIn("qacey-internal", mcp_service)

    def test_backend_json_format_and_private_url_posture_remain(self):
        settings = (REPO_ROOT / "infrastructure/searxng/settings.yml").read_text(
            encoding="utf-8"
        )
        agent_config = (REPO_ROOT / "services/agent/config.shared.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- html", settings)
        self.assertIn("- json", settings)
        self.assertIn("allow_private_urls: false", agent_config)

    def test_deployment_seeds_config_and_env_only_when_missing(self):
        self.assertIn("seed_config_yaml()", self.deploy)
        self.assertIn("seed_runtime_env()", self.deploy)
        self.assertIn('instance=justin seed_config_yaml "$JUSTIN_DATA/config.yaml"', self.deploy)
        self.assertIn('instance=annique seed_config_yaml "$ANNIQUE_DATA/config.yaml"', self.deploy)
        self.assertNotIn("hermes_state_merge", self.deploy)
        self.assertNotIn('"$HERMES_SRC/mcp-servers.shared.json"', self.deploy)
        self.assertNotIn('"$HERMES_SRC/mcp-servers.justin.json"', self.deploy)
        self.assertNotIn('"$HERMES_SRC/mcp-servers.annique.json"', self.deploy)

    def test_negative_guards_reject_public_or_stdio_shape(self):
        service = self.compose.split("  mcp-searxng:\n", 1)[1].split(
            "\n  # ── U-03:", 1
        )[0]
        self.assertNotRegex(service, r"(?m)^\s+ports:\s*$")
        self.assertNotIn('command: "uvx"', service)
        self.assertNotIn("MCP_SEARXNG_IMAGE=isokoliuk/mcp-searxng:latest", self.versions)


if __name__ == "__main__":
    unittest.main()