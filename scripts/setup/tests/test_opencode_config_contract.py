import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "infrastructure" / "opencode" / "config"
CONFIG = CONFIG_DIR / "opencode.json"
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"


class OpenCodeConfigContractTests(unittest.TestCase):
    def test_role_defaults_use_deepseek_for_implementation_and_uncapped_sol_for_review(self):
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "openai/gpt-6.2-sol")
        self.assertIn("-opencode.provider.openai-context-caps", data["plugins"])
        self.assertNotIn("small_model", data)
        implementation_roles = ("build", "general", "explore", "compaction", "title", "summary")
        review_roles = ("plan", "planner", "reviewer")
        for role in (*implementation_roles, *review_roles):
            with self.subTest(role=role):
                model = data["agents"][role]["model"]
                if model.startswith("{file:"):
                    pin = Path(model.removeprefix("{file:").removesuffix("}")).name
                    model = (CONFIG_DIR / "model-pins" / pin).read_text().strip()
                expected = (
                    "opencode-go/deepseek-v4.1-flash#high"
                    if role in implementation_roles else "openai/gpt-6.2-sol#high"
                )
                self.assertEqual(model, expected)

    def test_config_is_valid_and_has_research_mcp(self):
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        servers = data["mcp"]["servers"]
        self.assertEqual(
            servers["academic-papers"]["url"],
            "http://mcp-academic-papers:8000/mcp",
        )
        self.assertIn("context7", servers)
        self.assertIn("qacey-docker-control", servers)

    def test_credentials_and_runtime_state_are_not_tracked(self):
        names = {path.name for path in CONFIG_DIR.iterdir()}
        self.assertNotIn("service.json", names)
        self.assertNotIn("auth.json", names)
        self.assertNotIn("opencode.db", names)

    def test_retired_skills_and_commands_are_absent(self):
        skills = CONFIG_DIR / "skills"
        for name in (
            "megacave",
            "ultracave",
            "gstack-qa",
            "research-lookup",
            "livebench-eval",
            "linting-neostandard-eslint9",
        ):
            self.assertFalse((skills / name).exists(), name)

    def test_gstack_lenses_are_not_global_and_deny_rules_stay_in_force(self):
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertFalse(any("gstack" in source for source in data.get("skills", [])))
        commands = {
            path.name
            for path in (CONFIG_DIR / "commands").iterdir()
            if path.is_file()
        }
        self.assertFalse(any(name.startswith("gstack-") for name in commands))
        forbidden = {
            rule["resource"]
            for rule in data["permissions"]
            if rule["action"] == "skill" and rule["effect"] == "deny"
        }
        for name in (
            "gstack-ship",
            "gstack-land-and-deploy",
            "gstack-autoplan",
            "gstack-upgrade",
            "gstack-qa",
            "gstack-browse",
        ):
            self.assertIn(name, forbidden)

    def test_workflow_plugins_are_project_local_and_reusable_skills_stay_global(self):
        global_data = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertFalse(any("superpowers" in entry for entry in global_data["plugins"]))
        project_data = json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(
            project_data["plugins"],
            ["superpowers@git+https://github.com/obra/superpowers.git#v7.0.2"],
        )
        self.assertEqual(
            {path.parent.name for path in (CONFIG_DIR / "skills").glob("*/SKILL.md")},
            {"caveman", "citation-verification", "literature-review", "typescript-magician"},
        )

    def test_compose_sets_gstack_runtime(self):
        text = COMPOSE.read_text(encoding="utf-8")
        self.assertIn(
            "GSTACK_ROOT: /home/opencode/.local/share/gstack/home/.config/opencode/skills/gstack",
            text,
        )
        self.assertIn('GSTACK_SKIP_PLAYWRIGHT: "1"', text)

    def test_compose_mounts_the_config_read_only(self):
        text = COMPOSE.read_text(encoding="utf-8")
        for relative in (
            "opencode.json",
            "codebase-index.json",
            "instructions",
            "model-pins",
            "skills",
            "commands",
        ):
            mount = (
                f"./infrastructure/opencode/config/{relative}:"
                f"/home/opencode/.config/opencode/{relative}:ro"
            )
            self.assertIn(mount, text)

    def test_research_mcp_is_on_the_opencode_network(self):
        text = COMPOSE.read_text(encoding="utf-8")
        block = text.split("  mcp-academic-papers:\n", 1)[1].split(
            "  # ── U-06: mnemo-postgres", 1
        )[0]
        self.assertIn("qacey-opencode-mcp", block)


if __name__ == "__main__":
    unittest.main()
