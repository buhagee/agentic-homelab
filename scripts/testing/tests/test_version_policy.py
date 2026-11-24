import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = REPO_ROOT / "versions.env"
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"

MANAGED_VARIABLES = (
    "TRAEFIK_VERSION",
    "CLOUDFLARED_VERSION",
    "WIREGUARD_VERSION",
    "ADGUARD_VERSION",
    "OLLAMA_VERSION",
    "CROWDSEC_VERSION",
    "OAUTH2_PROXY_VERSION",
    "HERMES_WEBUI_VERSION",
    "IMMICH_VERSION",
    "VAULTWARDEN_VERSION",
    "SEARXNG_VERSION",
    "HOMEASSISTANT_VERSION",
    "REDIS_VERSION",
    "CRAWL4AI_VERSION",
    "PAPERLESS_VERSION",
    "SCRUTINY_VERSION",
    "POSTGRES_VERSION",
    "OPENCODE_V2_VERSION",
)


class VersionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.versions = VERSIONS.read_text(encoding="utf-8")
        self.compose = COMPOSE.read_text(encoding="utf-8")

    def test_postgres_uses_a_pinned_variable(self):
        self.assertIn("POSTGRES_VERSION=", self.versions)
        self.assertIn("postgres:${POSTGRES_VERSION}", self.compose)

    def test_data_store_images_are_digest_pinned(self):
        for variable in (
            "IMMICH_POSTGRES_VERSION",
            "MNEMO_PGVECTOR_VERSION",
            "POSTGRES_VERSION",
            "REDIS_VERSION",
        ):
            value = re.search(
                rf"(?m)^{re.escape(variable)}=(.+)$",
                self.versions,
            )
            self.assertIsNotNone(value, variable)
            self.assertIn("@sha256:", value.group(1), variable)

    def test_no_managed_image_uses_latest(self):
        for variable in MANAGED_VARIABLES:
            value = re.search(rf"(?m)^{re.escape(variable)}=(.+)$", self.versions)
            self.assertIsNotNone(value, variable)
            self.assertNotIn("latest", value.group(1), variable)

    def test_every_managed_variable_has_a_renovate_annotation(self):
        for variable in MANAGED_VARIABLES:
            self.assertRegex(
                self.versions,
                rf"(?m)^# renovate: .*\n{re.escape(variable)}=",
                variable,
            )

    def test_no_annotation_points_at_a_local_image(self):
        self.assertNotRegex(self.versions, r"(?m)^# renovate: .*qacey/")

    def test_every_annotated_package_is_in_a_renovate_rule(self):
        config = json.loads(
            (REPO_ROOT / "renovate.json").read_text(encoding="utf-8")
        )
        governed = set()
        for rule in config["packageRules"]:
            governed.update(rule.get("matchPackageNames", []))
        pattern = config["customManagers"][0]["matchStrings"][0]
        pattern = re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", pattern)
        for match in re.finditer(pattern, self.versions):
            self.assertIn(match.group("packageName"), governed)

    def test_compose_has_no_latest_image(self):
        self.assertNotIn(":latest", self.compose)

    def test_env_example_does_not_override_image_versions(self):
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotRegex(env_example, r"(?m)^[A-Z0-9_]+VERSION=")

    def test_custom_manager_regex_matches_every_annotation(self):
        config = json.loads(
            (REPO_ROOT / "renovate.json").read_text(encoding="utf-8")
        )
        pattern = config["customManagers"][0]["matchStrings"][0]
        pattern = re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", pattern)
        matches = list(re.finditer(pattern, self.versions))
        self.assertEqual(len(matches), len(MANAGED_VARIABLES))
        packages = {match.group("packageName") for match in matches}
        for expected in (
            "traefik",
            "ghcr.io/paperless-ngx/paperless-ngx",
            "postgres",
        ):
            self.assertIn(expected, packages)


if __name__ == "__main__":
    unittest.main()
