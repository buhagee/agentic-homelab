import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "services" / "agent" / "config.shared.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
DEPLOY = REPO_ROOT / "scripts" / "deploy" / "deploy-agent-config.sh"


class AgentMediaProviderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = CONFIG.read_text(encoding="utf-8")
        cls.env = ENV_EXAMPLE.read_text(encoding="utf-8")
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.deploy = DEPLOY.read_text(encoding="utf-8")

    def test_image_generation_is_explicit_and_not_confused_with_vision(self):
        self.assertIn("image_gen:", self.config)
        self.assertIn("provider: openrouter", self.config)
        self.assertIn("model: ${HERMES_IMAGE_GEN_MODEL}", self.config)
        self.assertIn("max_parallel_requests: ${HERMES_IMAGE_GEN_MAX_PARALLEL_REQUESTS}", self.config)
        self.assertIn("HERMES_IMAGE_GEN_MODEL=google/gemini-2.5-flash-image", self.env)
        self.assertIn("OPENROUTER_API_KEY: ${OPENROUTER_API_KEY}", self.compose)
        self.assertNotIn("FAL_KEY: ${FAL_KEY}", self.compose)

    def test_hermes_agents_do_not_configure_telegram(self):
        self.assertNotIn("TELEGRAM_BOT_TOKEN: ${", self.compose)
        self.assertNotIn("TELEGRAM_ALLOWED_USERS:", self.compose)
        self.assertNotIn("telegram:", self.config)

    def test_runtime_env_carries_generation_settings_without_logging_secrets(self):
        self.assertNotIn("HERMES_IMAGE_GEN_MODEL:-google/gemini-2.5-flash-image", self.deploy)
        self.assertNotIn("OPENCODE_GO_BASE_URL:-", self.deploy)
        self.assertIn("--managed-key HERMES_IMAGE_GEN_MODEL", self.deploy)
        self.assertIn("--managed-key OPENCODE_GO_BASE_URL", self.deploy)
        self.assertIn("write_runtime_env \"$JUSTIN_DATA/.env\"", self.deploy)
        self.assertIn("write_runtime_env \"$ANNIQUE_DATA/.env\"", self.deploy)
        self.assertIn("hermes_state_merge.py", self.deploy)
        self.assertNotIn("FAL_KEY=", self.deploy)
        self.assertNotIn("TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN_", self.compose)
        proxy = (REPO_ROOT / "services" / "skillclaw" / "proxy-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("sed 's/", proxy)
        self.assertIn("api_key:", proxy)
        self.assertIn("***", proxy)

    def test_skillclaw_uses_opencode_go_relay(self):
        self.assertIn("OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1", self.env)
        self.assertIn("SKILLCLAW_MODEL=deepseek-v4-flash", self.env)
        self.assertIn("OPENAI_API_KEY: ${OPENCODE_GO_API_KEY}", self.compose)
        self.assertIn("OPENAI_BASE_URL: ${OPENCODE_GO_BASE_URL}", self.compose)
        self.assertIn("EVOLVE_MODEL: ${SKILLCLAW_MODEL}", self.compose)

    def test_hermes_base_image_is_pinned(self):
        versions = (REPO_ROOT / "versions.env").read_text(encoding="utf-8")
        self.assertRegex(versions, r"HERMES_VERSION=v(?:2026\.\d+\.\d+|0\.\d+\.\d+)")
        dockerfile = (REPO_ROOT / "services" / "agent" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG HERMES_VERSION", dockerfile)
        self.assertIn("FROM nousresearch/hermes-agent:${HERMES_VERSION}", dockerfile)
        self.assertIn("HERMES_VERSION: ${HERMES_VERSION}", self.compose)


if __name__ == "__main__":
    unittest.main()
