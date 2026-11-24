import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "renovate.json"

STATELESS = {
    "traefik",
    "cloudflare/cloudflared",
    "searxng/searxng",
    "unclecode/crawl4ai",
    "ghcr.io/analogj/scrutiny",
    "quay.io/oauth2-proxy/oauth2-proxy",
}
STATEFUL = {
    "nousresearch/hermes-agent",
    "ghcr.io/immich-app/immich-server",
    "ghcr.io/immich-app/immich-machine-learning",
    "ghcr.io/immich-app/postgres",
    "ghcr.io/paperless-ngx/paperless-ngx",
    "postgres",
    "pgvector/pgvector",
    "redis",
    "ghcr.io/nesquena/hermes-webui",
    "vaultwarden/server",
    "ghcr.io/home-assistant/home-assistant",
    "crowdsecurity/crowdsec",
    "adguard/adguardhome",
    "lscr.io/linuxserver/wireguard",
    "ollama/ollama",
}


class RenovatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_custom_manager_reads_versions_env(self):
        manager = self.config["customManagers"][0]
        self.assertEqual(manager["customType"], "regex")
        self.assertEqual(self.config["enabledManagers"], ["custom.regex"])
        self.assertTrue(
            any("versions" in pattern and "env" in pattern for pattern in manager["managerFilePatterns"])
        )

    def test_stateless_patch_and_minor_automerge(self):
        rules = [
            rule
            for rule in self.config["packageRules"]
            if "stateless" in rule.get("addLabels", [])
        ]
        self.assertTrue(rules)
        matched = set()
        for rule in rules:
            matched.update(rule.get("matchPackageNames", []))
            self.assertIn(rule.get("matchUpdateTypes"), (["patch"], ["minor"]))
            self.assertTrue(rule.get("automerge", False))
        self.assertEqual(matched, STATELESS)

    def test_pr_creation_is_not_throttled(self):
        self.assertEqual(self.config["prHourlyLimit"], 0)

    def test_platform_automerge_is_enabled(self):
        self.assertTrue(self.config["platformAutomerge"])

    def test_top_level_automerge_is_disabled(self):
        self.assertFalse(self.config["automerge"])

    def test_stateful_packages_never_automerge(self):
        stateful_rules = [
            rule
            for rule in self.config["packageRules"]
            if "stateful" in rule.get("addLabels", [])
        ]
        self.assertTrue(stateful_rules)
        matched = set()
        for rule in stateful_rules:
            self.assertFalse(rule.get("automerge", False))
            matched.update(rule.get("matchPackageNames", []))
        self.assertEqual(matched, STATEFUL)

    def test_major_updates_never_automerge(self):
        major_rules = [
            rule
            for rule in self.config["packageRules"]
            if rule.get("matchUpdateTypes") == ["major"]
        ]
        self.assertTrue(major_rules)
        for rule in major_rules:
            if "anomalyco/opencode" in rule.get("matchPackageNames", []):
                continue
            self.assertFalse(rule.get("automerge", False))

    def test_vulnerability_alerts_enabled(self):
        self.assertTrue(self.config["vulnerabilityAlerts"]["enabled"])

    def test_workflow_uses_a_github_app_token(self):
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "renovate.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("actions/create-github-app-token@v3", workflow)
        self.assertIn("client-id: ${{ vars.RENOVATE_APP_CLIENT_ID }}", workflow)
        self.assertIn("secrets.RENOVATE_APP_PRIVATE_KEY", workflow)
        self.assertNotIn("RENOVATE_TOKEN", workflow)

    def test_renovate_runs_once_a_day(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "renovate.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('cron: "0 18 * * *"', workflow)

    def opencode_rules(self):
        return [
            rule
            for rule in self.config["packageRules"]
            if "anomalyco/opencode" in rule.get("matchPackageNames", [])
        ]

    def test_opencode_patch_automerge_is_immediate(self):
        rule = next(r for r in self.opencode_rules() if r.get("matchUpdateTypes") == ["patch"])
        self.assertTrue(rule["automerge"])
        self.assertNotIn("minimumReleaseAge", rule)
        self.assertNotIn("platformAutomerge", rule)

    def test_opencode_minor_waits_two_days(self):
        rule = next(r for r in self.opencode_rules() if r.get("matchUpdateTypes") == ["minor"])
        self.assertTrue(rule["automerge"])
        self.assertFalse(rule["platformAutomerge"])
        self.assertEqual(rule["minimumReleaseAge"], "2 days")

    def test_opencode_major_waits_a_week(self):
        rule = next(r for r in self.opencode_rules() if r.get("matchUpdateTypes") == ["major"])
        self.assertTrue(rule["automerge"])
        self.assertFalse(rule["platformAutomerge"])
        self.assertEqual(rule["minimumReleaseAge"], "7 days")

    def test_ci_runs_the_opencode_smoke_job(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("opencode-smoke:", workflow)
        self.assertIn("opencode --version", workflow)

    def test_ruleset_requires_the_smoke_check(self):
        ruleset = (REPO_ROOT / "scripts" / "setup" / "github-main-ruleset.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"context": "opencode-smoke"', ruleset)


if __name__ == "__main__":
    unittest.main()
