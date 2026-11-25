import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "infrastructure/codex"


def load_script(test, name, path):
    test.assertTrue(path.is_file(), f"missing entry point: {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.launch = load_script(self, "launcher", ASSETS / "qacey-codex.py")
        self.runtime = load_script(self, "runtime", ASSETS / "install_runtime.py")
        self.common = sys.modules["codex_account"]
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory())) / "ssd" / "dev agent"
        self.projects = self.home / "projects"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.projects.mkdir()
        self.state = self.home / ".codex"
        self.state.mkdir()
        record = self.home.parent / "installation.json"
        record.write_text(json.dumps(dict(schema=1, user="dev-agent", home=str(self.home),
                                          uid=1023, gid=1024, ready=True)))
        self.enterContext(patch.object(self.common, "RECORD", record))
        self.enterContext(patch.object(self.common, "ROOT_UID", os.geteuid()))
        self.enterContext(patch.object(os, "geteuid", return_value=1023))
        identity = pwd.struct_passwd(("dev-agent", "x", 1023, 1024, "", str(self.home), "/bin/bash"))
        self.enterContext(patch.object(pwd, "getpwnam", return_value=identity))
        self.enterContext(patch.object(os, "getegid", return_value=1024))
        self.enterContext(patch.object(os, "getgroups", return_value=[1024]))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(redirect_stderr(io.StringIO()))
        self.log = self.home / "calls.json"
        self.codex = self.bin / "codex"
        self.codex.write_text(
            '#!/usr/bin/python3\nimport json, os, pathlib, sys\n'
            'pathlib.Path(os.environ["HOME"], "calls.json").write_text(json.dumps('
            'dict(args=sys.argv[1:], env=dict(os.environ), cwd=os.getcwd())))\n'
            'sys.exit(7)\n'
        )
        self.codex.chmod(0o700)

    def call(self):
        return json.loads(self.log.read_text())

    def test_lifecycle_invocations_use_one_identity_and_return_cli_status(self):
        for command, args in {
            "version": ["--version"], "login": ["login", "--device-auth"],
            "login-status": ["login", "status"], "start": ["remote-control", "start", "--json"],
            "stop": ["remote-control", "stop", "--json"], "pair": ["remote-control", "pair"],
            "status": ["app-server", "daemon", "version"],
        }.items():
            with self.subTest(command=command), patch.dict(os.environ, HOME="/root", CODEX_HOME="/other"):
                self.assertEqual(self.launch.main([command]), 7)
                call = self.call()
                self.assertEqual(call["args"], args)
                self.assertEqual(call["env"]["HOME"], str(self.home))
                self.assertEqual(call["env"]["CODEX_HOME"], str(self.state))
                self.assertEqual(call["cwd"], str(self.home))

    def git(self, *args):
        subprocess.run(["/usr/bin/git", *map(str, args)], check=True, capture_output=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"})

    def repo(self, name, parent=None):
        project = (parent or self.projects) / name
        self.git("init", project)
        self.git("-C", project, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--allow-empty", "-m", "test")
        return project

    def test_run_preserves_spaces_and_accepts_worktrees_of_a_development_clone(self):
        source = self.repo("repo with spaces")
        project = self.projects / "linked dev checkout"
        self.git("-C", source, "worktree", "add", "--detach", project)
        with patch.dict(os.environ, GIT_DIR="/bogus", GIT_WORK_TREE="/elsewhere", GIT_COMMON_DIR="/"):
            self.assertEqual(self.launch.main(["run", str(project)]), 7)
        self.assertEqual(self.call()["args"], ["-C", str(project)])
        self.assertFalse(any(key.startswith("GIT_") for key in self.call()["env"]))

    def test_run_rejects_external_git_common_dir_even_with_inherited_git_overrides(self):
        external = self.repo("operator-repo", self.home.parent)
        linked = self.projects / "linked"
        self.git("-C", external, "worktree", "add", "--detach", linked)
        decoy = self.repo("decoy")
        with patch.dict(os.environ, GIT_DIR=str(decoy / ".git"), GIT_WORK_TREE=str(decoy)):
            with self.assertRaises((ValueError, RuntimeError)):
                self.launch.main(["run", str(linked)])
        self.assertFalse(self.log.exists())

    def test_run_rejects_external_symlinks_root_nonrepo_and_extra_args(self):
        external = self.repo("operator", self.home.parent)
        link = self.projects / "link"
        link.symlink_to(external)
        plain = self.projects / "empty"
        plain.mkdir()
        for path in (external, link, self.projects, plain):
            with self.subTest(path=path), self.assertRaises((ValueError, RuntimeError)):
                self.launch.main(["run", str(path)])
        good = self.repo("inside")
        with self.assertRaises(SystemExit):
            self.launch.main(["run", str(good), "-C", str(external)])
        self.assertFalse(self.log.exists())

    def test_run_rejects_relocated_projects_root(self):
        self.projects.rmdir()
        self.projects.symlink_to(self.home.parent)
        project = self.repo("operator", self.home.parent)
        with self.assertRaises((ValueError, RuntimeError)):
            self.launch.main(["run", str(self.projects / project.name)])
        self.assertFalse(self.log.exists())

    def test_wrong_account_and_root_rejected_before_runtime_download_or_exec(self):
        with patch.object(self.runtime, "urlopen", side_effect=AssertionError("network used")):
            for uid in (0, 1088):
                with self.subTest(uid=uid), patch.object(os, "geteuid", return_value=uid):
                    for entry, args in ((self.runtime.main, ["--apply"]), (self.launch.main, ["version"])):
                        with self.assertRaises((ValueError, RuntimeError, PermissionError)):
                            entry(args)
        self.assertFalse(self.log.exists())

    def test_runtime_dry_run_and_launcher_forwarding_do_not_download_or_execute(self):
        with patch.object(self.runtime, "urlopen", side_effect=AssertionError("network used")):
            self.assertEqual(self.runtime.main([]), 0)
        with patch.object(self.launch.install_runtime, "main", return_value=42) as install:
            for args in ([], ["--apply"]):
                self.assertEqual(self.launch.main(["install-runtime", *args]), 42)
                self.assertEqual(install.call_args.args, (args,))
        self.assertFalse(self.log.exists())

    def test_runtime_rejects_unreviewed_installer_without_execution(self):
        release = json.loads((ASSETS / "release.json").read_text())
        self.assertEqual(release, {
            "version": "0.172.0", "url": "https://chatgpt.com/codex/install.sh",
            "sha256": "b698d8eb50c0fbe0214ea57b5bf2af439054108404c6d2b872989db02f4bd574"
        })
        with patch.object(self.runtime, "urlopen", return_value=io.BytesIO(b"exit 0\n")), \
             patch.object(subprocess, "run", side_effect=AssertionError("ran before hash check")):
            with self.assertRaisesRegex((RuntimeError, ValueError), "(?i)checksum|sha-?256"):
                self.runtime.main(["--apply"])

    def run_fixture_installer(self, result_version):
        script = ("""set -eu
test "$1" = --release
test "$2" = 0.172.0
test "$CODEX_NON_INTERACTIVE" = 1
test "$CODEX_HOME" = "$HOME/.codex"
test "$CODEX_INSTALL_DIR" = "$HOME/.local/bin"
test "${PATH%%:*}" = "$CODEX_INSTALL_DIR"
test -z "${CODEX_INSTALL_DAEMON_ONLY:-}"
test "$(stat -c %a "$(dirname "$0")")" = 700
printf '%s\\n' '#!/bin/sh' 'echo codex-cli VERSION' > "$CODEX_INSTALL_DIR/codex"
chmod 700 "$CODEX_INSTALL_DIR/codex"
""".replace("VERSION", result_version)).encode()
        release = self.home / "release.json"
        release.write_text(json.dumps(dict(version="0.172.0", url="https://example.invalid",
                                           sha256=hashlib.sha256(script).hexdigest())))
        with patch.object(self.runtime, "RELEASE", release), \
             patch.object(self.runtime, "urlopen", return_value=io.BytesIO(script)), \
             patch.dict(os.environ, CODEX_INSTALL_DAEMON_ONLY="1", CODEX_HOME="/other"):
            return self.runtime.main(["--apply"])

    def test_runtime_installs_full_pinned_release_with_controlled_environment(self):
        self.assertEqual(self.run_fixture_installer("0.172.0"), 0)

    def test_runtime_rejects_an_installed_prerelease_or_other_version(self):
        with self.assertRaisesRegex((RuntimeError, ValueError), "(?i)version"):
            self.run_fixture_installer("0.172.0-alpha.1")

    def test_privileged_supplementary_group_is_rejected_at_launch(self):
        with patch.object(os, "getgroups", return_value=[1024, 999]):
            with self.assertRaises((RuntimeError, ValueError, PermissionError)):
                self.launch.main(["version"])
        self.assertFalse(self.log.exists())
