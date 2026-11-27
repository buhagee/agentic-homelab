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
    "caddy",
}
STATEFUL = {
    "ghcr.io/immich-app/immich-server",
    "ghcr.io/immich-app/immich-machine-learning",
    "ghcr.io/immich-app/postgres",
    "ghcr.io/paperless-ngx/paperless-ngx",
    "postgres",
    "pgvector/pgvector",
    "redis",
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
            if rule.get("matchUpdateTypes") == ["minor"]:
                self.assertEqual(rule.get("minimumReleaseAge"), "2 days")
        self.assertEqual(matched, STATELESS)

    def test_pr_creation_is_not_throttled(self):
        self.assertEqual(self.config["prHourlyLimit"], 0)

    def test_platform_automerge_is_enabled(self):
        self.assertTrue(self.config["platformAutomerge"])

    def test_top_level_automerge_is_enabled(self):
        self.assertTrue(self.config["automerge"])

    def test_stateful_packages_automerge_patch_and_minor(self):
        stateful_rules = [
            rule
            for rule in self.config["packageRules"]
            if "stateful" in rule.get("addLabels", [])
        ]
        self.assertTrue(stateful_rules)
        matched = set()
        for rule in stateful_rules:
            self.assertTrue(rule.get("automerge", False))
            matched.update(rule.get("matchPackageNames", []))
        self.assertEqual(matched, STATEFUL)

    def test_stateful_major_rule_overrides_stateful_automerge(self):
        rules = self.config["packageRules"]
        stateful_index = next(
            index
            for index, rule in enumerate(rules)
            if "stateful" in rule.get("addLabels", [])
        )
        major_index = next(
            index
            for index, rule in enumerate(rules)
            if rule.get("matchUpdateTypes") == ["major"]
        )
        self.assertLess(stateful_index, major_index)
        self.assertFalse(rules[major_index].get("automerge", False))

    def test_major_updates_never_automerge(self):
        major_rules = [
            rule
            for rule in self.config["packageRules"]
            if rule.get("matchUpdateTypes") == ["major"]
        ]
        self.assertTrue(major_rules)
        for rule in major_rules:
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

    def test_ci_runs_the_opencode_smoke_job(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("opencode-smoke:", workflow)
        self.assertIn("scripts/testing/check-dev-runtime.py", workflow)

    def test_ruleset_requires_the_smoke_check(self):
        ruleset = (REPO_ROOT / "scripts" / "setup" / "github-main-ruleset.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"context": "opencode-smoke"', ruleset)

    def test_openchamber_release_is_tracked_and_automerges_patch_minor(self):
        managers = [
            m for m in self.config["customManagers"]
            if m.get("depNameTemplate") == "@openchamber/web"
        ]
        self.assertEqual(len(managers), 1)
        self.assertEqual(managers[0]["datasourceTemplate"], "npm")
        rules = [
            rule for rule in self.config["packageRules"]
            if "@openchamber/web" in rule.get("matchPackageNames", [])
        ]
        self.assertEqual(len(rules), 3)
        default_rule, minor_rule, major_rule = rules
        self.assertTrue(default_rule["automerge"])
        self.assertIn(
            "python3 scripts/maintenance/refresh-openchamber-release.py {{{newVersion}}}",
            default_rule["postUpgradeTasks"]["commands"],
        )
        self.assertEqual(minor_rule["matchUpdateTypes"], ["minor"])
        self.assertEqual(minor_rule["minimumReleaseAge"], "2 days")
        self.assertEqual(major_rule["matchUpdateTypes"], ["major"])
        self.assertFalse(major_rule["automerge"])

    def test_all_minor_updates_have_two_day_minimum_release_age(self):
        minor_rules = [
            rule
            for rule in self.config["packageRules"]
            if rule.get("matchUpdateTypes") == ["minor"]
        ]
        self.assertTrue(minor_rules)
        for rule in minor_rules:
            self.assertEqual(rule.get("minimumReleaseAge"), "2 days")

    def test_renovate_workflow_runs_native_runtime_updater(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "renovate.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("native-runtime:", workflow)
        self.assertIn("native-runtime-publish:", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("scripts/maintenance/update-native-runtime.py", workflow)
        self.assertIn("scripts/testing/check-dev-runtime.py", workflow)
        self.assertIn("renovate/native-runtime", workflow)
        self.assertIn("renovate/native-runtime-major", workflow)


if __name__ == "__main__":
    unittest.main()
