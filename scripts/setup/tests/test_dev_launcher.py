import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'infrastructure/dev-agent'


def load(name, path):
    sys.path.insert(0, str(ASSETS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ASSETS / 'qacey-dev.py').exists(), 'missing native development launcher')
        self.launcher = load('test_qacey_dev', ASSETS / 'qacey-dev.py')
        self.context = self.launcher.dev_context
        self.real_current = self.context.current
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home.chmod(0o700)
        self.account = self.context.foundation.Account('dev-agent', self.home)
        for path in ('.codex', '.local/bin', 'projects', '.config/qacey-dev'):
            (self.home / path).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.record = {'schema': 1, 'ready': True, 'user': 'dev-agent', 'uid': os.geteuid(),
                       'gid': os.getegid(), 'home': str(self.home), 'port': 3939,
                       'node': '/usr/bin/node', 'opencode_version': '2.4.1', 'openchamber_version': '2.8.0'}
        self.enterContext(patch.object(self.context, 'current', return_value=(self.account, self.record)))
        self.output = self.enterContext(redirect_stdout(io.StringIO()))

    def project(self, name='example'):
        path = self.home / 'projects' / name
        path.mkdir()
        subprocess.run(['/usr/bin/git', '-C', str(path), 'init', '-q'], check=True)
        return path

    def test_record_is_root_owned_ready_and_matches_current_identity(self):
        target = self.home / 'development-installation.json'
        target.write_text(json.dumps(self.record))
        target.chmod(0o644)
        with patch.object(self.context, 'RECORD', target), patch.object(self.context, 'ROOT_UID', os.geteuid()), patch.object(self.context.foundation, 'current_account', return_value=self.account):
            self.assertEqual(self.real_current()[0], self.account)
            changed = dict(self.record, uid=os.geteuid() + 1)
            target.write_text(json.dumps(changed))
            with self.assertRaises(ValueError): self.real_current()
            target.write_text(json.dumps(self.record))
            target.chmod(0o666)
            with self.assertRaises(ValueError): self.real_current()
            target.unlink()
            target.symlink_to(self.home / 'elsewhere')
            with self.assertRaises(ValueError): self.real_current()

    def test_identity_is_checked_before_runtime_install(self):
        with patch.object(self.context, 'current', side_effect=PermissionError('wrong user')):
            with patch.object(subprocess, 'run') as run, self.assertRaises(PermissionError):
                self.launcher.main(['install-runtime', '--apply'])
            run.assert_not_called()

    def test_codex_client_cannot_start_a_second_tmux_server(self):
        project = self.project('space and ; shell')
        real = subprocess.run
        calls = []
        def run(argv, **kwargs):
            if argv[0] == '/usr/bin/git': return real(argv, **kwargs)
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, '', '')
        with patch.object(subprocess, 'run', side_effect=run):
            self.assertEqual(self.launcher.main(['codex', str(project)]), 0)
            self.assertEqual(self.launcher.main(['codex', str(project)]), 0)
        self.assertEqual(calls[0][0], calls[1][0])
        argv = calls[0][0]
        self.assertIn('-N', argv)
        self.assertEqual(argv[argv.index('-S') + 1], '/run/qacey-codex-tmux/server.sock')
        self.assertIn('new-session', argv)
        self.assertIn('-A', argv)
        self.assertEqual(argv[-3:], ['/usr/local/bin/qacey-dev', '_codex-run', str(project)])
        self.assertNotIn('shell', calls[0][1])

    def test_project_outside_dev_root_and_shared_production_git_metadata_rejected(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory()))
        subprocess.run(['/usr/bin/git', '-C', str(outside), 'init', '-q'], check=True)
        with self.assertRaises(ValueError): self.launcher.main(['codex', str(outside)])
        fake = self.home / 'projects/linked'
        fake.mkdir()
        (fake / '.git').write_text('gitdir: ' + str(outside / '.git') + '\n')
        with self.assertRaises(ValueError): self.launcher.main(['codex', str(fake)])

    def test_codex_child_loads_current_mcp_values_without_secret_argv(self):
        project = self.project()
        (self.home / '.config/qacey-dev/mcp-env.json').write_text(json.dumps({'MCP_TOKEN': 'private-test-value'}))
        (self.home / '.config/qacey-dev/mcp-env.json').chmod(0o600)
        with patch.object(self.context.sync_config, 'managed_env_names', return_value={'MCP_TOKEN'}), patch.object(os, 'execve') as execute, patch.object(os, 'chdir'):
            self.launcher.main(['_codex-run', str(project)])
        executable, argv, env = execute.call_args.args
        self.assertEqual(env['MCP_TOKEN'], 'private-test-value')
        self.assertNotIn('private-test-value', repr(argv) + self.output.getvalue())
        self.assertEqual(argv, [str(self.account.codex), '-C', str(project)])
        self.assertEqual(executable, self.account.codex)

    def test_mcp_environment_is_explicit_private_and_cannot_override_harness(self):
        secret = self.home / '.config/qacey-dev/mcp-env.json'
        for name in ('PATH', 'NODE_OPTIONS', 'LD_PRELOAD', 'BASH_ENV', 'OPENAI_API_KEY', 'OPENCODE_PORT', 'CODEX_HOME'):
            with self.subTest(name=name), patch.object(self.context.sync_config, 'managed_env_names', return_value={name}):
                with self.assertRaises(ValueError): self.context.environment(self.account)
        secret.write_text('{"UNSHARED": "do-not-print"}')
        secret.chmod(0o600)
        with patch.object(self.context.sync_config, 'managed_env_names', return_value={'MCP_TOKEN'}):
            with self.assertRaises(ValueError) as caught: self.context.environment(self.account)
            self.assertNotIn('do-not-print', str(caught.exception))
            secret.write_text('{"MCP_TOKEN": "do-not-print"}')
            secret.chmod(0o644)
            with self.assertRaises(ValueError): self.context.environment(self.account)
            secret.unlink()
            secret.symlink_to(self.home / '.codex/config.toml')
            with self.assertRaises(ValueError): self.context.environment(self.account)

    def test_openchamber_requires_secrets_and_does_not_adopt_backend(self):
        runtime = {'opencode': self.home / 'runtime/opencode', 'openchamber': self.home / 'runtime/web', 'node': Path('/usr/bin/node')}
        with patch.object(self.context, 'runtime_selection', return_value=runtime), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): self.launcher.main(['openchamber'])
        with patch.object(self.context, 'runtime_selection', return_value=runtime), patch.object(os, 'execve') as execute, patch.object(os, 'chdir'):
            with patch.dict(os.environ, {'OPENCHAMBER_UI_PASSWORD': 'u' * 32, 'OPENCODE_PASSWORD': 'p' * 32,
                                        'OPENCODE_HOST': 'http://other:4096', 'OPENCODE_PORT': '4096', 'OPENCODE_JWT_SECRET': 'unexpected'}, clear=True):
                self.launcher.main(['openchamber'])
            _, argv, env = execute.call_args.args
        self.assertEqual(argv[-6:], ['serve', '--foreground', '--host', '127.0.0.1', '--port', '3939'])
        self.assertNotIn('--api-only', argv)
        self.assertEqual(env['OPENCHAMBER_OPENCODE_HOSTNAME'], '127.0.0.1')
        self.assertEqual(env['OPENCODE_DISABLE_AUTOUPDATE'], '1')
        for name in ('OPENCODE_HOST', 'OPENCODE_PORT', 'OPENCODE_SKIP_START', 'OPENCODE_JWT_SECRET'):
            self.assertNotIn(name, env)
        self.assertEqual(env['OPENCHAMBER_UI_PASSWORD'], 'u' * 32)
        self.assertNotIn('u' * 32, repr(argv))

    def test_shared_service_setting_refused_before_startup(self):
        data = self.home / '.config/openchamber'
        data.mkdir()
        (data / 'settings.json').write_text('{"useGlobalOpenCodeService":true}')
        with self.assertRaises(ValueError): self.context.check_openchamber_settings(self.account)

    def test_sync_creates_only_empty_portable_skills_directory_on_apply(self):
        with patch.object(self.launcher.sync_config, 'sync', return_value=[]):
            self.launcher.main(['sync'])
            self.assertFalse((self.home / '.agents').exists())
            self.launcher.main(['sync', '--apply'])
            self.assertTrue((self.home / '.agents/skills').is_dir())
            self.assertEqual(list((self.home / '.agents/skills').iterdir()), [])

    def test_status_is_read_only_and_does_not_dump_logs_or_environment(self):
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.launcher.main(['status'])
        command = run.call_args.args[0]
        self.assertIn('show', command)
        self.assertIn('--property=Id,ActiveState,SubState,UnitFileState', command)
        self.assertNotIn('restart', command)


class GuidanceSeedTests(unittest.TestCase):
    def setUp(self):
        self.seed = load('test_qacey_shared_seed', ROOT / 'infrastructure/codex/seed_home.py')
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home.chmod(0o700)
        self.seed.main(self.home)
        self.shared = self.home / '.config/qacey-dev/AGENTS.md'
        self.shared.parent.mkdir(parents=True, mode=0o700)
        self.shared.write_text('shared user guidance')
        self.shared.chmod(0o600)
        self.entry = self.home / '.codex/AGENTS.md'
        self.entry.unlink()

    def test_exact_shared_link_survives_foundation_rerun(self):
        self.entry.symlink_to(self.shared)
        self.seed.main(self.home)
        self.assertTrue(self.entry.is_symlink())
        self.assertEqual(self.shared.read_text(), 'shared user guidance')

    def test_other_link_or_redirected_target_is_rejected(self):
        other = self.home / 'other'
        other.write_text('unchanged')
        self.entry.symlink_to(other)
        with self.assertRaises(ValueError): self.seed.main(self.home)
        self.entry.unlink()
        self.entry.symlink_to(self.shared)
        self.shared.unlink()
        self.shared.symlink_to(other)
        with self.assertRaises(ValueError): self.seed.main(self.home)
        self.assertEqual(other.read_text(), 'unchanged')

    def test_shared_guidance_with_unsafe_permissions_is_rejected(self):
        self.entry.symlink_to(self.shared)
        self.shared.chmod(0o666)
        with self.assertRaises(ValueError): self.seed.main(self.home)


if __name__ == '__main__': unittest.main()
