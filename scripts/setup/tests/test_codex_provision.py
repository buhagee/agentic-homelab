import configparser
import grp
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        entry = ROOT / "scripts/setup/install-codex.py"
        self.assertTrue(entry.is_file(), "missing root provisioning entry point")
        spec = importlib.util.spec_from_file_location("provision_codex", entry)
        self.setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.setup)
        self.host = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.host_uid = os.geteuid()
        self.uid, self.gid = self.host_uid or 60001, os.getegid() or 60001
        self.host.chmod(0o711)
        self.home = self.host / "mnt/local ssd/dev agent"
        self.lib = self.host / "usr/local/lib/qacey-codex"
        self.launcher = self.host / "usr/local/bin/qacey-codex"
        self.record = self.host / "etc/qacey-codex/installation.json"
        self.unit = self.host / "etc/systemd/system/qacey-codex.service"
        for parent in (self.home.parent, self.lib.parent, self.launcher.parent, self.unit.parent, self.host / "home"):
            parent.mkdir(parents=True, exist_ok=True)
        for parent in self.host.rglob("*/"):
            parent.chmod(0o755)
        self.enterContext(patch.object(self.setup, "HOST_ROOT", self.host))
        self.enterContext(patch.object(self.setup, "ROOT_UID", self.host_uid))
        self.args = ["--user", "dev-agent", "--home", str(self.home)]
        self.account = None
        self.passwd_entries = []
        self.group = None
        self.groups = [self.gid]
        self.locked = "L"
        self.commands = []
        self.fail_seed = False
        self.real_run = subprocess.run
        self.enterContext(patch.object(subprocess, "run", side_effect=self.run_boundary))

        def lookup(attr):
            def get(name):
                obj = getattr(self, attr)
                if name != "dev-agent" or obj is None:
                    raise KeyError(name)
                return obj
            return get

        self.enterContext(patch.object(pwd, "getpwnam", side_effect=lookup("account")))
        self.enterContext(patch.object(pwd, "getpwall", side_effect=self.passwd_entries.copy))
        self.enterContext(patch.object(grp, "getgrnam", side_effect=lookup("group")))
        self.enterContext(patch.object(os, "getgrouplist", side_effect=lambda *_: self.groups))
        self.enterContext(redirect_stdout(io.StringIO()))

    def run_boundary(self, argv, **opts):
        cmd = Path(argv[0]).name
        self.commands.append(cmd)
        if cmd == "useradd":
            self.assertIn("--no-create-home", argv)
            self.assertIn("--user-group", argv)
            self.assertEqual(argv[argv.index("--groups") + 1], "")
            self.assertEqual(argv[argv.index("--password") + 1], "!")
            self.assertEqual(argv[argv.index("--home-dir") + 1], str(self.home))
            self.assertEqual(argv[-1], "dev-agent")
            self.account = pwd.struct_passwd(("dev-agent", "x", self.uid, self.gid,
                                              argv[argv.index("--comment") + 1], str(self.home), "/bin/bash"))
            self.passwd_entries.append(self.account)
            self.group = grp.struct_group(("dev-agent", "x", self.gid, []))
        elif cmd == "passwd":
            return subprocess.CompletedProcess(argv, 0, f"dev-agent {self.locked} 01/01/2026 0 99 7 -1\n", "")
        elif cmd == "python3":
            self.assertEqual(opts["user"], self.uid)
            self.assertEqual(opts["group"], self.gid)
            self.assertEqual(opts["extra_groups"], [])
            if self.host_uid != 0:
                # Already running unprivileged. setgroups(2) itself would require root.
                for key in ("user", "group", "extra_groups"):
                    del opts[key]
            if self.fail_seed:
                raise RuntimeError("interrupted seeding")
            return self.real_run(argv, capture_output=True, **opts)
        else:
            self.fail(f"unexpected system command: {argv!r}")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def apply(self):
        return self.setup.main([*self.args, "--apply"])

    def test_default_stage_is_read_only(self):
        before = sorted(self.host.rglob("*"))
        self.assertEqual(self.setup.main(self.args), 0)
        self.assertEqual(sorted(self.host.rglob("*")), before)
        self.assertEqual(self.commands, [])

    def test_apply_requires_root(self):
        with patch.object(os, "geteuid", return_value=self.uid + 1):
            with self.assertRaises((RuntimeError, PermissionError)):
                self.apply()
        self.assertFalse(self.home.exists())
        self.assertEqual(self.commands, [])

    def test_provisions_user_only_state_and_managed_lifecycle_as_disabled(self):
        self.assertEqual(self.apply(), 0)
        record = json.loads(self.record.read_text())
        self.assertEqual((record["user"], record["home"], record["uid"], record["gid"], record["ready"]),
                         ("dev-agent", str(self.home), self.uid, self.gid, True))
        for directory in (self.home, self.home / "projects", self.home / ".codex", self.home / ".local/bin"):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        config_path = self.home / ".codex/config.toml"
        self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o600)
        self.assertEqual(tomllib.loads(config_path.read_text()), {
            "approval_policy": "on-request", "approvals_reviewer": "user", "sandbox_mode": "workspace-write",
            "cli_auth_credentials_store": "file", "sandbox_workspace_write": {
                "network_access": True, "writable_roots": [str(self.home / "projects")]}})
        self.assertTrue((self.home / ".codex/AGENTS.md").is_file())
        self.assertTrue(os.access(self.launcher, os.X_OK))
        self.assertTrue((self.lib / "install_runtime.py").is_file())
        unit = configparser.ConfigParser(interpolation=None)
        unit.read(self.unit)
        service = unit["Service"]
        self.assertEqual(service["User"], "dev-agent")
        self.assertEqual(service["Group"], "dev-agent")
        self.assertEqual(service["Type"], "oneshot")
        self.assertEqual(service["RemainAfterExit"], "yes")
        for directive, action in {"ExecCondition": "login-status", "ExecStart": "start", "ExecStop": "stop"}.items():
            self.assertEqual(service[directive], f"/usr/local/bin/qacey-codex {action}")
        self.assertEqual(int(service["UMask"], 8), 0o77)
        self.assertIn("TimeoutStartSec", service)
        stop_seconds = int(service["TimeoutStopSec"].removesuffix("s"))
        self.assertGreater(stop_seconds, 375 + 300 + 10 + 10)  # lock, grace, PID init, forced exit
        self.assertFalse(any(self.host.rglob("*.wants")))
        self.assertFalse((self.home / ".codex/auth.json").exists())

    def test_rerun_preserves_credentials_and_user_config_while_refreshing_helpers(self):
        self.apply()
        for name in ("auth.json", "config.toml", "AGENTS.md"):
            (self.home / ".codex" / name).write_text(f"user-owned {name}")
        helper = self.lib / "install_runtime.py"
        helper.write_text("outdated")
        self.apply()
        for name in ("auth.json", "config.toml", "AGENTS.md"):
            self.assertEqual((self.home / ".codex" / name).read_text(), f"user-owned {name}")
        self.assertEqual(helper.read_bytes(), (ROOT / "infrastructure/codex/install_runtime.py").read_bytes())
        self.assertEqual(self.commands.count("useradd"), 1)

    def test_resume_after_interrupted_seeding_reuses_the_recorded_account(self):
        self.fail_seed = True
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.apply()
        self.assertFalse(json.loads(self.record.read_text())["ready"])
        self.fail_seed = False
        self.apply()
        self.assertTrue(json.loads(self.record.read_text())["ready"])
        self.assertEqual(self.commands.count("useradd"), 1)

    def test_rejects_unrelated_account_group_or_home_before_any_mutations(self):
        for name in ("account", "group", "home"):
            with self.subTest(name=name):
                if name == "home":
                    self.home.mkdir()
                else:
                    setattr(self, name, object())
                with self.assertRaises((RuntimeError, ValueError)):
                    self.apply()
                self.assertFalse(self.record.exists())
                self.assertEqual(self.commands, [])
                if name != "home":
                    setattr(self, name, None)

    def test_rejects_symlink_ancestors_and_unowned_artifacts_before_useradd(self):
        for destination in (self.home, self.lib, self.launcher, self.unit, self.record.parent):
            with self.subTest(destination=destination):
                destination.symlink_to(self.host / "missing-target")
                with self.assertRaises((RuntimeError, ValueError)):
                    self.apply()
                self.assertEqual(self.commands, [])
                destination.unlink()
        self.unit.write_text("another install")
        with self.assertRaises((RuntimeError, ValueError)):
            self.apply()
        self.assertEqual(self.unit.read_text(), "another install")
        self.assertEqual(self.commands, [])
        self.unit.unlink()
        self.home.parent.chmod(0o777)
        with self.assertRaises((RuntimeError, ValueError)):
            self.apply()
        self.assertEqual(self.commands, [])

    def test_rejects_dangerous_account_home_and_noncanonical_inputs(self):
        for user, home in (("root", str(self.home)), ("-user", str(self.home)), ("a\nb", str(self.home)),
                           ("dev-agent", "/"), ("dev-agent", "relative"), ("dev-agent", str(self.host / "etc/new")),
                           ("dev-agent", f"{self.home.parent}/../other"), ("dev-agent", f"{self.home}/")):
            with self.subTest(user=user, home=home), self.assertRaises((RuntimeError, ValueError, SystemExit)):
                self.setup.main([f"--user={user}", "--home", home, "--apply"])
        self.assertEqual(self.commands, [])
        self.assertFalse(self.record.exists())

    def test_platform_storage_overlap_is_rejected_even_for_missing_homes(self):
        for disk in ("ssd", "hdd1", "hdd2"):
            mount = self.host / "mnt" / disk
            for location in (mount, mount / "qacey", mount / "qacey/deep/dev-agent"):
                with self.subTest(location=location), self.assertRaisesRegex(ValueError, "platform"):
                    self.setup.main(["--home", str(location), "--apply"])
            alternative = mount / "dev-agent"
            self.assertEqual(self.setup.checked_home("dev-agent", str(alternative)), alternative)
        self.assertFalse(self.record.exists())
        self.assertFalse(self.commands)

    def test_unsearchable_home_ancestor_rejected_before_account_or_record_creation(self):
        (self.host / "mnt").chmod(0o700)
        before = sorted(self.host.rglob("*"))
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(sorted(self.host.rglob("*")), before)
        self.assertIsNone(self.account)
        self.assertFalse(self.record.exists())
        self.assertEqual(self.commands, [])

    def test_rerun_rejects_another_account_with_the_private_primary_gid(self):
        self.apply()
        self.passwd_entries.append(pwd.struct_passwd(
            ("other", "x", self.uid + 1, self.gid, "", str(self.host / "home/other"), "/bin/bash")))
        self.commands.clear()
        record = self.record.read_bytes()
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.record.read_bytes(), record)
        self.assertEqual(self.commands, [])

    def test_existing_account_privilege_drift_and_symlink_substitution_fail_closed(self):
        self.apply()
        self.groups.append(self.gid + 1)
        with self.assertRaises((ValueError, RuntimeError)):
            self.apply()
        self.groups.pop()
        self.locked = "P"
        with self.assertRaises((ValueError, RuntimeError)):
            self.apply()
        self.locked = "L"
        path = self.lib / "install_runtime.py"
        path.unlink()
        outside = self.host / "untouched"
        outside.write_text("unchanged")
        path.symlink_to(outside)
        with self.assertRaises((ValueError, RuntimeError)):
            self.apply()
        self.assertEqual(outside.read_text(), "unchanged")

    def test_restrictive_operator_umask_still_allows_user_to_read_system_helpers(self):
        old = os.umask(0o077)
        try:
            self.apply()
        finally:
            os.umask(old)
        for directory in (self.record.parent, self.lib):
            self.assertTrue(directory.stat().st_mode & stat.S_IXOTH)
        for file in (self.record, self.lib / "seed_home.py"):
            self.assertTrue(file.stat().st_mode & stat.S_IROTH)

    def test_empty_existing_record_directory_does_not_establish_ownership(self):
        self.record.parent.mkdir()
        with self.assertRaises((ValueError, RuntimeError)):
            self.apply()
        self.assertEqual(self.commands, [])

    def test_failed_refresh_blocks_runtime_until_reprovisioning_finishes(self):
        self.apply()
        self.fail_seed = True
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.apply()
        self.assertFalse(json.loads(self.record.read_text())["ready"])

    def test_first_install_refuses_a_preexisting_enablement_link(self):
        wants = self.unit.parent / "multi-user.target.wants"
        wants.mkdir()
        (wants / self.unit.name).symlink_to(self.unit)
        with self.assertRaises((ValueError, RuntimeError)):
            self.apply()
        self.assertFalse(self.unit.exists())
        self.assertEqual(self.commands, [])

    def test_first_install_refuses_units_dropins_and_links_in_other_systemd_load_paths(self):
        name = self.unit.name
        candidates = (
            ("usr/lib/systemd/system", name, "file"),
            ("usr/lib/systemd/system", f"multi-user.target.wants/{name}", "link"),
            ("run/systemd/system", f"{name}.d", "directory"),
            ("run/systemd/generator.late", f"default.target.requires/{name}", "link"),
            ("usr/local/lib/systemd/system", f"default.target.upholds/{name}", "link"),
            ("lib/systemd/system", name, "link"),
        )
        for location, entry, kind in candidates:
            path = self.host / location / entry
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == "link":
                path.symlink_to(self.unit)  # dangling links can activate the unit once installed
            elif kind == "directory":
                path.mkdir()
            else:
                path.write_text("[Unit]\nDescription=Vendor service\n")
            try:
                with self.subTest(path=path):
                    for argv in (self.args, [*self.args, "--apply"]):
                        with self.assertRaises(ValueError):
                            self.setup.main(argv)
                    self.assertFalse(self.record.exists())
                    self.assertFalse(self.home.exists())
                    self.assertEqual(self.commands, [])
            finally:
                if kind == "directory":
                    path.rmdir()
                else:
                    path.unlink()

    def test_default_plan_selects_an_isolated_home_and_projects(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(self.setup.main([]), 0)
        self.assertIn("Dedicated account: dev-agent", output.getvalue())
        self.assertIn(str(self.host / "home/dev-agent/projects"), output.getvalue())
        self.assertFalse((self.host / "home/dev-agent").exists())

    def test_existing_user_state_symlink_is_never_followed_by_root_or_seed(self):
        self.apply()
        state = self.home / ".codex"
        state.rename(self.home / "preserved")
        outside = self.host / "operator"
        outside.mkdir()
        state.symlink_to(outside)
        with self.assertRaises(subprocess.CalledProcessError):
            self.apply()
        self.assertEqual(list(outside.iterdir()), [])

    def test_preexisting_unit_overrides_are_not_adopted(self):
        overrides = self.unit.with_suffix(".service.d")
        overrides.mkdir()
        (overrides / "other.conf").write_text("[Service]\nUser=root\n")
        with self.assertRaises((ValueError, RuntimeError)):
            self.apply()
        self.assertEqual(self.commands, [])
        self.assertFalse(self.record.exists())
