import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER = REPO_ROOT / "scripts" / "lib" / "hermes_state_merge.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("hermes_state_merge", HELPER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ConfigMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_helper()

    def test_preserves_mcp_and_plugins_blocks(self):
        base = "model:\n  provider: opencode-go\n"
        live = (
            "model:\n  provider: old\n"
            "mcp_servers:\n  searxng:\n    url: http://mcp-searxng:3000/mcp\n"
            "plugins:\n  enabled:\n    - mcp-serve\n"
        )

        result = self.helper.merge_config(base, live)

        self.assertIn("mcp_servers:", result)
        self.assertIn("plugins:", result)
        self.assertIn("provider: opencode-go", result)
        self.assertNotIn("provider: old", result)

    def test_writes_base_only_when_live_is_missing(self):
        base = "model:\n  provider: opencode-go\n"

        self.assertEqual(self.helper.merge_config(base, ""), base)

    def test_rejects_ui_owned_key_in_base(self):
        base = "mcp_servers:\n  stale:\n    url: http://stale\n"

        with self.assertRaises(ValueError):
            self.helper.merge_config(base, "")

    def test_rejects_duplicate_live_block(self):
        live = "plugins:\n  enabled: []\nplugins:\n  enabled: []\n"

        with self.assertRaises(ValueError):
            self.helper.merge_config("model:\n  provider: x\n", live)

    def test_preserves_only_ui_owned_blocks(self):
        base = "model:\n  provider: opencode-go\nmemory:\n  memory_enabled: true\n"
        live = (
            "model:\n  provider: ui-edit\n"
            "memory:\n  memory_enabled: false\n"
            "mcp_servers:\n  one:\n    url: http://one\n"
            "plugins:\n  enabled:\n    - one\n"
            "dashboard:\n  public_url: https://ui.example\n"
        )

        result = self.helper.merge_config(base, live)

        self.assertIn("provider: opencode-go", result)
        self.assertNotIn("provider: ui-edit", result)
        self.assertIn("memory_enabled: true", result)
        self.assertNotIn("memory_enabled: false", result)
        self.assertNotIn("dashboard:", result)

    def test_preserves_comments_and_nested_lines(self):
        base = "model:\n  provider: opencode-go\n"
        live = (
            "mcp_servers:\n"
            "  # keep this comment\n"
            "  one:\n"
            "    url: http://one\n"
            "\n"
            "plugins:\n"
            "  enabled:\n"
            "    - one\n"
        )

        result = self.helper.merge_config(base, live)

        self.assertIn("  # keep this comment", result)
        self.assertIn("    url: http://one", result)

    def test_config_cli_preserves_live_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.yaml"
            live = Path(tmp) / "live.yaml"
            out = Path(tmp) / "out.yaml"
            base.write_text("model:\n  provider: opencode-go\n", encoding="utf-8")
            live.write_text(
                "mcp_servers:\n  one:\n    url: http://one\n"
                "plugins:\n  enabled:\n    - one\n",
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "config",
                    "--base",
                    str(base),
                    "--live",
                    str(live),
                    "--output",
                    str(out),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            result = out.read_text(encoding="utf-8")
            self.assertIn("mcp_servers:", result)
            self.assertIn("plugins:", result)
            self.assertIn("provider: opencode-go", result)


class EnvMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_helper()

    def test_updates_managed_key_and_preserves_ui_keys(self):
        existing = (
            "# UI comment\n"
            "OPENROUTER_API_KEY=old\n"
            "LINEAR_TOKEN=ui-token\n"
            "\n"
            "MCP_SERVER_KEY=kept\n"
        )

        result = self.helper.merge_env(existing, {"OPENROUTER_API_KEY": "new"})

        self.assertIn("OPENROUTER_API_KEY=new", result)
        self.assertNotIn("OPENROUTER_API_KEY=old", result)
        self.assertIn("LINEAR_TOKEN=ui-token", result)
        self.assertIn("MCP_SERVER_KEY=kept", result)
        self.assertIn("# UI comment", result)

    def test_empty_managed_value_removes_stale_key(self):
        result = self.helper.merge_env(
            "OPENROUTER_API_KEY=old\nLINEAR_TOKEN=ui\n",
            {"OPENROUTER_API_KEY": ""},
        )

        self.assertIn("OPENROUTER_API_KEY=\n", result)
        self.assertNotIn("OPENROUTER_API_KEY=old", result)
        self.assertIn("LINEAR_TOKEN=ui", result)

    def test_special_characters_are_written_verbatim(self):
        value = 'abc # not a comment $x "quoted" \'single\''

        result = self.helper.merge_env("", {"MCP_TOKEN": value})

        self.assertEqual(result, f"MCP_TOKEN={value}\n")

    def test_rejects_newline_in_value(self):
        with self.assertRaises(ValueError):
            self.helper.merge_env("", {"MCP_TOKEN": "one\ntwo"})

    def test_rejects_invalid_key(self):
        with self.assertRaises(ValueError):
            self.helper.merge_env("", {"bad-key": "value"})

    def test_env_cli_reads_value_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / ".env"
            out = Path(tmp) / ".env.new"
            existing.write_text(
                "OPENROUTER_API_KEY=old\nLINEAR_TOKEN=ui\n", encoding="utf-8"
            )
            env = os.environ.copy()
            env["OPENROUTER_API_KEY"] = "new"

            subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "env",
                    "--existing",
                    str(existing),
                    "--output",
                    str(out),
                    "--managed-key",
                    "OPENROUTER_API_KEY",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            result = out.read_text(encoding="utf-8")
            self.assertIn("OPENROUTER_API_KEY=new", result)
            self.assertIn("LINEAR_TOKEN=ui", result)


class AtomicWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_helper()

    def test_write_sets_mode_600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"

            self.helper.write_text_atomic(path, "model:\n  provider: x\n")

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
