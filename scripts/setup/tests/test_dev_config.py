import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "infrastructure/dev-agent"


class SharedConfigTests(unittest.TestCase):
    def setUp(self):
        path = ASSETS / "sync_config.py"
        self.assertTrue(path.is_file(), "missing shared configuration synchronizer")
        self.enterContext(patch.object(sys, "path", [str(ASSETS), *sys.path]))
        spec = importlib.util.spec_from_file_location("dev_sync", path)
        self.sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sync)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "dev account"
        self.home.mkdir()
        self.source = self.root / "baseline"
        self.source.mkdir()
        self.guidance = "# Shared development\nKeep one writer per worktree.\n"
        (self.source / "AGENTS.md").write_text(self.guidance)
        self.manifest = {"schema": 1, "servers": {
            "context7": {"transport": "http", "url": "https://mcp.context7.com/mcp"},
            "local": {"transport": "stdio", "command": "{home}/.local/bin/helper",
                      "args": ["--project", "a project"], "cwd": "{home}/projects",
                      "env_vars": ["EXAMPLE_TOKEN"], "enabled": False},
            "private": {"transport": "http", "url": "https://mcp.example.invalid/mcp",
                        "bearer_token_env_var": "PRIVATE_TOKEN",
                        "env_http_headers": {"X-Workspace": "WORKSPACE_ID"}},
        }}
        self.save_source()
        self.codex = self.home / ".codex/config.toml"
        self.opencode = self.home / ".config/opencode/opencode.json"
        self.shared = self.home / ".config/qacey-dev/AGENTS.md"
        self.state = self.home / ".config/qacey-dev/sync-state.json"
        self.pending = self.home / ".config/qacey-dev/sync-pending.json"

    def save_source(self):
        (self.source / "mcp.json").write_text(json.dumps(self.manifest))

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def apply(self):
        return self.sync.sync(self.home, self.source, apply=True)

    def configs(self):
        return tomllib.loads(self.codex.read_text()), json.loads(self.opencode.read_text())

    def snapshot(self):
        return {str(p.relative_to(self.home)): (p.lstat().st_mtime_ns,
                os.readlink(p) if p.is_symlink() else p.read_bytes())
                for p in self.home.rglob("*") if p.is_symlink() or p.is_file()}

    def test_dry_run_is_read_only_and_redacted(self):
        self.put(self.opencode, json.dumps({"provider": {"apiKey": "private-native-value"}}))
        before = self.snapshot()
        with patch.dict(os.environ, PRIVATE_TOKEN="actual-token-never-read"):
            result = self.sync.sync(self.home, self.source)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(any("context7" in line for line in result))
        self.assertFalse(any("private-native-value" in line or "actual-token" in line for line in result))

    def test_supported_transports_and_environment_references_are_native(self):
        self.apply()
        codex, opencode = self.configs()
        c = codex["mcp_servers"]
        o = opencode["mcp"]["servers"]
        self.assertEqual(c["context7"], {"url": "https://mcp.context7.com/mcp", "enabled": True})
        self.assertEqual(c["local"], {"command": str(self.home / ".local/bin/helper"),
            "args": ["--project", "a project"], "cwd": str(self.home / "projects"),
            "env_vars": ["EXAMPLE_TOKEN"], "enabled": False})
        self.assertEqual(o["local"], {"type": "local", "command": [str(self.home / ".local/bin/helper"),
            "--project", "a project"], "cwd": str(self.home / "projects"),
            "environment": {"EXAMPLE_TOKEN": "{env:EXAMPLE_TOKEN}"}, "disabled": True})
        self.assertEqual(c["private"]["bearer_token_env_var"], "PRIVATE_TOKEN")
        self.assertEqual(c["private"]["env_http_headers"], {"X-Workspace": "WORKSPACE_ID"})
        self.assertEqual(o["private"]["headers"], {"Authorization": "Bearer {env:PRIVATE_TOKEN}",
                                                    "X-Workspace": "{env:WORKSPACE_ID}"})
        self.assertNotIn("oauth", o["private"])
        self.assertEqual(self.shared.read_text(), self.guidance)
        for entry in (self.home / ".codex/AGENTS.md", self.home / ".config/opencode/AGENTS.md"):
            self.assertTrue(entry.is_symlink())
            self.assertEqual(entry.resolve(), self.shared)

    def test_repeat_is_noop_and_does_not_rewrite_files(self):
        self.apply()
        before = self.snapshot()
        self.assertEqual(self.apply(), [])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.pending.exists())

    def test_unrelated_settings_servers_and_client_oauth_survive_update(self):
        codex_original = '# My model\nmodel = "choice"\n\n[mcp_servers.personal]\nurl = "https://personal.invalid/mcp"\n'
        self.put(self.codex, codex_original)
        self.put(self.opencode, json.dumps({"model": "provider/choice", "plugins": ["personal-plugin"],
            "permissions": [{"action": "shell", "resource": "*", "effect": "ask"}],
            "mcp": {"servers": {"personal": {"type": "remote", "url": "https://personal.invalid/mcp"}}}}))
        self.apply()
        self.codex.write_text(self.codex.read_text().replace(
            'url = "https://mcp.context7.com/mcp"',
            'url = "https://mcp.context7.com/mcp"\noauth_client_id = "client-specific"'))
        o = json.loads(self.opencode.read_text())
        o["mcp"]["servers"]["context7"]["oauth"] = {"clientId": "client-specific"}
        o["plugins"].append("ui-added")
        self.opencode.write_text(json.dumps(o))
        self.manifest["servers"]["context7"]["enabled"] = False
        self.save_source()
        self.apply()
        c, after = self.configs()
        self.assertIn(codex_original, self.codex.read_text())
        self.assertEqual(c["mcp_servers"]["context7"]["oauth_client_id"], "client-specific")
        self.assertFalse(c["mcp_servers"]["context7"]["enabled"])
        self.assertEqual(after["plugins"], ["personal-plugin", "ui-added"])
        self.assertEqual(after["model"], "provider/choice")
        self.assertEqual(after["permissions"], o["permissions"])
        self.assertEqual(after["mcp"]["servers"]["context7"]["oauth"], {"clientId": "client-specific"})
        self.assertEqual(after["mcp"]["servers"]["personal"], o["mcp"]["servers"]["personal"])

    def test_conflicting_managed_edit_stops_before_other_config_writes(self):
        self.apply()
        o = json.loads(self.opencode.read_text())
        o["mcp"]["servers"]["context7"]["url"] = "https://edited.invalid/mcp"
        self.opencode.write_text(json.dumps(o))
        self.manifest["servers"]["context7"]["url"] = "https://baseline.invalid/mcp"
        self.save_source()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "conflict|changed"):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_removes_only_previously_managed_servers(self):
        self.apply()
        o = json.loads(self.opencode.read_text())
        o["mcp"]["servers"]["ui-added"] = {"type": "remote", "url": "https://ui.invalid/mcp"}
        self.opencode.write_text(json.dumps(o))
        del self.manifest["servers"]["local"]
        self.save_source()
        self.apply()
        c, o = self.configs()
        self.assertNotIn("local", c["mcp_servers"])
        self.assertNotIn("local", o["mcp"]["servers"])
        self.assertIn("ui-added", o["mcp"]["servers"])

    def test_removal_with_local_client_fields_requires_explicit_resolution(self):
        self.apply()
        o = json.loads(self.opencode.read_text())
        o["mcp"]["servers"]["context7"]["oauth"] = False
        self.opencode.write_text(json.dumps(o))
        del self.manifest["servers"]["context7"]
        self.save_source()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "conflict|local"):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_preexisting_named_server_is_not_silently_adopted(self):
        for target, content in ((self.codex, '[mcp_servers.context7]\nurl="https://custom.invalid/mcp"\n'),
                                (self.opencode, '{"mcp":{"servers":{"context7":{"type":"remote","url":"https://custom.invalid/mcp"}}}}')):
            with self.subTest(target=target):
                self.put(target, content)
                with self.assertRaisesRegex(ValueError, "conflict|already|unmanaged"):
                    self.apply()
                self.assertEqual(target.read_text(), content)
                target.unlink()

    def test_existing_jsonc_is_rejected_without_rewriting(self):
        for text in ('// personal settings\n{}', '{}'):
            target = self.opencode.with_suffix(".jsonc")
            self.put(target, text)
            with self.assertRaisesRegex(ValueError, "JSONC|jsonc"):
                self.apply()
            self.assertEqual(target.read_text(), text)
            self.assertFalse(self.opencode.exists())

    def test_invalid_manifest_and_duplicate_json_keys_fail_without_config_writes(self):
        invalid = [
            {"schema": 2, "servers": {}}, {"schema": True, "servers": {}},
            {"schema": 1, "servers": {}, "extra": 1},
            {"schema": 1, "servers": {"a": {"transport": []}}},
            {"schema": 1, "servers": {"invalid.name": {"transport": "http", "url": "https://a.invalid"}}},
            {"schema": 1, "servers": {"a": {"transport": "http", "url": "https://u:secret@a.invalid"}}},
            {"schema": 1, "servers": {"a": {"transport": "http", "url": "https://a.invalid?token=secret"}}},
            {"schema": 1, "servers": {"a": {"transport": "http", "url": "file:///tmp/tool"}}},
            {"schema": 1, "servers": {"a": {"transport": "http", "url": "https://a.invalid:bad"}}},
            {"schema": 1, "servers": {"a": {"transport": "stdio", "command": "tool", "env": {"KEY": "literal"}}}},
            {"schema": 1, "servers": {"a": {"transport": "stdio", "command": "tool", "env_vars": ["bad-name"]}}},
            {"schema": 1, "servers": {"a": {"transport": "http", "url": "https://a.invalid", "enabled": "false"}}},
            {"schema": 1, "servers": {"a": {"transport": "http", "url": "https://a.invalid", "bearer_token_env_var": "TOKEN", "env_http_headers": {"authorization": "OTHER"}}}},
        ]
        for manifest in invalid:
            with self.subTest(manifest=manifest):
                (self.source / "mcp.json").write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    self.apply()
                self.assertFalse(self.codex.exists())
                self.assertFalse(self.opencode.exists())
        (self.source / "mcp.json").write_text('{"schema":1,"schema":1,"servers":{}}')
        with self.assertRaises(ValueError):
            self.apply()

    def test_unmodified_foundation_guidance_migrates_but_edited_guidance_does_not(self):
        entry = self.home / ".codex/AGENTS.md"
        original = (ROOT / "infrastructure/codex/AGENTS.md.in").read_text()
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), self.sync.LEGACY_GUIDANCE_SHA256)
        self.put(entry, original + "\nMy local rule\n")
        with self.assertRaisesRegex(ValueError, "guidance|AGENTS"):
            self.apply()
        self.assertFalse(entry.is_symlink())
        entry.write_text(original)
        self.apply()
        self.assertEqual(entry.resolve(), self.shared)

    def test_shared_guidance_edit_is_preserved_until_promoted(self):
        self.apply()
        self.shared.write_text("# Locally edited shared rule\n")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "guidance|AGENTS|conflict"):
            self.apply()
        self.assertEqual(self.snapshot(), before)
        (self.source / "AGENTS.md").write_text(self.shared.read_text())
        self.apply()
        self.assertEqual(self.shared.read_text(), "# Locally edited shared rule\n")

    def test_symlinked_parent_file_and_guidance_collision_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.home / ".config").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink|real directory"):
            self.apply()
        self.assertEqual(list(outside.iterdir()), [])
        (self.home / ".config").unlink()
        target = outside / "config.json"
        target.write_text('{"model":"keep"}')
        self.opencode.parent.mkdir(parents=True)
        self.opencode.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink|regular"):
            self.apply()
        self.assertEqual(target.read_text(), '{"model":"keep"}')
        self.opencode.unlink()
        entry = self.home / ".config/opencode/AGENTS.md"
        entry.symlink_to(outside / "AGENTS.md")
        with self.assertRaisesRegex(ValueError, "guidance|AGENTS|symlink"):
            self.apply()

    def test_native_parse_errors_do_not_disclose_config_contents(self):
        for target, value in ((self.codex, 'token = "sensitive\n'),
                              (self.opencode, '{"sensitive-native-value": invalid}')):
            with self.subTest(target=target):
                self.put(target, value)
                with self.assertRaises(ValueError) as caught:
                    self.apply()
                self.assertNotIn("sensitive", str(caught.exception))
                target.unlink()

    def test_interrupted_apply_resumes_same_baseline_without_losing_local_values(self):
        self.put(self.opencode, '{"plugins":["keep"],"provider":{"apiKey":"native-secret"}}')
        original = self.sync._replace
        calls = 0

        def interrupt(path, kind, content):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError("simulated interruption")
            return original(path, kind, content)

        with patch.object(self.sync, "_replace", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.apply()
        self.assertTrue(self.pending.is_file())
        self.assertNotIn("native-secret", self.pending.read_text())
        self.assertFalse(self.state.exists())
        self.apply()
        self.assertFalse(self.pending.exists())
        self.assertEqual(json.loads(self.opencode.read_text())["plugins"], ["keep"])
        self.assertEqual(self.apply(), [])

    def test_interrupted_apply_refuses_changed_source_or_post_interruption_edits(self):
        original = self.sync._replace

        def interrupt(path, kind, content):
            if path == self.codex:
                raise OSError("simulated interruption")
            return original(path, kind, content)

        with patch.object(self.sync, "_replace", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.apply()
        self.assertTrue(self.pending.exists())
        self.manifest["servers"]["context7"]["enabled"] = False
        self.save_source()
        with self.assertRaisesRegex(ValueError, "interrupted|baseline"):
            self.apply()
        del self.manifest["servers"]["context7"]["enabled"]
        self.save_source()
        self.shared.write_text("A new edit after interruption\n")
        with self.assertRaisesRegex(ValueError, "interrupted|changed"):
            self.apply()
        self.assertEqual(self.shared.read_text(), "A new edit after interruption\n")

    def test_file_changed_between_plan_and_apply_is_not_overwritten(self):
        self.put(self.opencode, '{"plugins":["before"]}')
        original = self.sync._replace

        def mutate(path, kind, content):
            if path == self.codex:
                self.opencode.write_text('{"plugins":["concurrent"]}')
            return original(path, kind, content)

        with patch.object(self.sync, "_replace", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "changed|conflict"):
                self.apply()
        self.assertEqual(json.loads(self.opencode.read_text())["plugins"], ["concurrent"])

    def test_exclusive_lock_and_private_written_files(self):
        lock = self.home / ".qacey-dev-sync.lock"
        with lock.open("w") as stream:
            lock.chmod(0o600)
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "running|lock|busy"):
                self.apply()
        self.apply()
        for path in (self.codex, self.opencode, self.shared, self.state, lock):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_managed_block_deleted_or_misplaced_is_a_conflict(self):
        self.apply()
        self.codex.write_text('model = "local"\n')
        with self.assertRaisesRegex(ValueError, "block|conflict|changed"):
            self.apply()

    def test_environment_reference_api_never_reads_values_and_refuses_pending_sync(self):
        self.assertEqual(self.sync.managed_env_names(self.home), set())
        self.apply()
        with patch.dict(os.environ, PRIVATE_TOKEN="hidden-value"):
            self.assertEqual(self.sync.managed_env_names(self.home),
                             {"PRIVATE_TOKEN", "EXAMPLE_TOKEN", "WORKSPACE_ID"})
        self.pending.write_text("{}")
        with self.assertRaisesRegex(ValueError, "interrupted"):
            self.sync.managed_env_names(self.home)

    def test_local_header_and_unrelated_table_after_codex_block_survive(self):
        self.apply()
        self.codex.write_text(self.codex.read_text() + '\n[mcp_servers.native]\ncommand="tool"\n')
        o = json.loads(self.opencode.read_text())
        o["mcp"]["servers"]["private"]["headers"]["X-Client"] = "local"
        self.opencode.write_text(json.dumps(o))
        self.manifest["servers"]["private"]["env_http_headers"]["X-Workspace"] = "NEXT_WORKSPACE"
        self.save_source()
        self.apply()
        c, o = self.configs()
        self.assertEqual(c["mcp_servers"]["native"], {"command": "tool"})
        self.assertEqual(o["mcp"]["servers"]["private"]["headers"]["X-Client"], "local")
        self.assertEqual(o["mcp"]["servers"]["private"]["headers"]["X-Workspace"], "{env:NEXT_WORKSPACE}")

    def test_update_interruption_after_state_commit_is_recoverable(self):
        self.apply()
        self.manifest["servers"]["context7"]["enabled"] = False
        self.save_source()
        original = Path.unlink

        def interrupt(path, *args, **kwargs):
            if path == self.pending:
                raise OSError("after state commit")
            return original(path, *args, **kwargs)

        with patch.object(Path, "unlink", interrupt):
            with self.assertRaisesRegex(OSError, "after state"):
                self.apply()
        before = self.snapshot()
        self.assertTrue(self.pending.is_file())
        self.apply()
        after = self.snapshot()
        before.pop(str(self.pending.relative_to(self.home)))
        self.assertEqual(after, before)

    def test_changed_owned_field_type_is_a_conflict(self):
        self.apply()
        o = json.loads(self.opencode.read_text())
        o["mcp"]["servers"]["context7"]["disabled"] = 0
        self.opencode.write_text(json.dumps(o))
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.apply()

    def test_corrupt_state_rejects_sync_and_environment_forwarding(self):
        self.apply()
        self.state.write_text("null")
        with self.assertRaisesRegex(ValueError, "state"):
            self.apply()
        with self.assertRaisesRegex(ValueError, "state"):
            self.sync.managed_env_names(self.home)

    def test_empty_manifest_and_guidance_only_repeat(self):
        self.manifest["servers"] = {}
        self.save_source()
        self.apply()
        self.assertEqual(self.apply(), [])
        self.assertEqual(self.shared.read_text(), self.guidance)


if __name__ == "__main__":
    unittest.main()
