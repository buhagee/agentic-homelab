import configparser
import grp
import io
import json
import os
from pathlib import Path
import pwd
import stat
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from test_dev_launcher import ROOT, ASSETS, load


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        entry = ROOT / 'scripts/setup/install-dev-agent.py'
        self.assertTrue(entry.exists(), 'missing development provisioner')
        self.setup = load('test_provision_dev', entry)
        import tempfile
        self.host = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.host.chmod(0o755)
        self.home = self.host / 'mnt/local ssd/dev % agent'
        self.home.mkdir(parents=True)
        self.home.chmod(0o700)
        self.uid, self.gid = os.geteuid(), os.getegid()
        self.user = pwd.struct_passwd(('dev-agent', 'x', self.uid, self.gid, 'qacey-codex-fixture', str(self.home), '/bin/bash'))
        self.group = grp.struct_group(('dev-agent', 'x', self.gid, []))
        for path in ('etc/qacey-codex', 'usr/local/lib/qacey-codex', 'usr/local/bin', 'etc/systemd/system'):
            (self.host / path).mkdir(parents=True, exist_ok=True)
        for path in self.host.rglob('*'):
            if path.is_dir() and path != self.home: path.chmod(0o755)
        self.foundation_record = {'schema': 1, 'ready': True, 'user': 'dev-agent', 'uid': self.uid,
                                  'gid': self.gid, 'home': str(self.home), 'marker': 'qacey-codex-fixture'}
        (self.host / 'etc/qacey-codex/installation.json').write_text(json.dumps(self.foundation_record))
        for name in ('codex_account.py', 'seed_home.py'):
            (self.host / 'usr/local/lib/qacey-codex' / name).write_bytes((ROOT / 'infrastructure/codex' / name).read_bytes())
        self.enterContext(patch.object(self.setup, 'HOST_ROOT', self.host))
        self.enterContext(patch.object(self.setup, 'ROOT_UID', self.uid))
        self.enterContext(patch.object(pwd, 'getpwnam', return_value=self.user))
        self.enterContext(patch.object(pwd, 'getpwall', return_value=[self.user]))
        self.enterContext(patch.object(grp, 'getgrnam', return_value=self.group))
        self.enterContext(patch.object(os, 'getgrouplist', return_value=[self.gid]))
        self.enterContext(patch.object(self.setup, 'source_version', return_value='a' * 40))
        self.commands = []
        import subprocess
        def run(argv, **kwargs):
            self.commands.append(argv)
            if argv[:2] == ['/usr/bin/passwd', '--status']:
                return subprocess.CompletedProcess(argv, 0, 'dev-agent L 01/01/2026 0 99 7 -1\n', '')
            self.fail('unexpected host command: ' + repr(argv))
        self.enterContext(patch.object(subprocess, 'run', side_effect=run))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.record = self.host / 'etc/qacey-dev/installation.json'

    def test_default_is_read_only_and_nonroot_apply_is_rejected(self):
        before = sorted(self.host.rglob('*'))
        self.assertEqual(self.setup.main([]), 0)
        self.assertEqual(sorted(self.host.rglob('*')), before)
        with patch.object(os, 'geteuid', return_value=self.uid + 1), self.assertRaises(PermissionError):
            self.setup.main(['--apply'])
        self.assertFalse(self.record.exists())

    def test_apply_installs_helpers_and_disabled_private_units_only(self):
        self.setup.main(['--apply'])
        record = json.loads(self.record.read_text())
        self.assertEqual((record['user'], record['home'], record['port'], record['node'], record['ready']),
                         ('dev-agent', str(self.home), 3939, '/usr/bin/node', True))
        self.assertEqual(record['source_version'], 'a' * 40)
        for name in ('mcp_config.py', 'sync_config.py', 'dev_context.py', 'install_runtime.py', 'shared/mcp.json', 'runtime/openchamber/package-lock.json'):
            self.assertTrue((self.host / 'usr/local/lib/qacey-dev' / name).is_file(), name)
        unit_dir = self.host / 'etc/systemd/system'
        web = configparser.ConfigParser(interpolation=None)
        web.read(unit_dir / 'qacey-openchamber.service')
        self.assertEqual(web['Service']['User'], 'dev-agent')
        self.assertEqual(web['Service']['EnvironmentFile'], '/etc/qacey-dev/openchamber.env')
        self.assertEqual(web['Service']['PrivateDevices'], 'true')
        self.assertEqual(web['Service']['ExecStart'], '/usr/local/bin/qacey-dev openchamber')
        self.assertEqual(web['Service']['WorkingDirectory'], '~')
        self.assertIn('dev %% agent', web['Service']['ReadWritePaths'])
        self.assertEqual(web['Service']['NoNewPrivileges'], 'true')
        socket = configparser.ConfigParser(interpolation=None)
        socket.read(unit_dir / 'qacey-dev-proxy.socket')
        self.assertEqual(socket['Socket']['SocketMode'], '0600')
        self.assertEqual(socket['Socket']['SocketUser'], 'dev-agent')
        self.assertEqual(socket['Socket']['ListenStream'], '/run/qacey-dev-proxy/backend.sock')
        tmux = (unit_dir / 'qacey-codex-tmux.service').read_text()
        self.assertIn('/usr/bin/tmux -D', tmux)
        self.assertIn('/run/qacey-codex-tmux/server.sock', tmux)
        self.assertNotIn('PartOf=qacey-openchamber', tmux)
        self.assertFalse(any(self.host.rglob('*.wants')))
        self.assertFalse((self.host / 'etc/qacey-dev/openchamber.env').exists())
        self.assertFalse((self.home / '.config').exists())
        self.assertTrue(all(command[0] == '/usr/bin/passwd' for command in self.commands))

    def test_policy_preserves_unrelated_values_and_rejects_conflicting_binary(self):
        directory = self.host / 'etc/openchamber'
        directory.mkdir()
        policy = directory / 'policy.json'
        policy.write_text('{"someExistingPolicy": true}')
        self.setup.main(['--apply'])
        data = json.loads(policy.read_text())
        self.assertTrue(data['someExistingPolicy'])
        self.assertNotEqual(data.get('enterpriseMode'), True)
        self.assertEqual(data['opencodeBinary'], str(self.home / '.local/share/qacey-dev/runtime/opencode-2.4.1/opencode'))
        data['opencodeBinary'] = '/unrelated/tool'
        policy.write_text(json.dumps(data))
        before = self.record.read_bytes()
        with self.assertRaises(ValueError): self.setup.main(['--apply'])
        self.assertEqual(self.record.read_bytes(), before)

    def test_reprovision_preserves_secrets_and_user_state_and_stopped_intent(self):
        self.setup.main(['--apply'])
        secret = self.host / 'etc/qacey-dev/openchamber.env'
        secret.write_text('operator-owned values')
        secret.chmod(0o600)
        before = sorted(self.home.rglob('*'))
        self.setup.main(['--port', '4949', '--node', '/opt/node/bin/node', '--apply'])
        self.assertEqual(secret.read_text(), 'operator-owned values')
        self.assertEqual(sorted(self.home.rglob('*')), before)
        self.assertEqual(json.loads(self.record.read_text())['port'], 4949)
        self.assertFalse(any(self.host.rglob('*.wants')))
        self.assertIn('127.0.0.1:4949', (self.host / 'etc/systemd/system/qacey-dev-proxy.service').read_text())

    def test_unrelated_files_symlinks_and_unit_dropins_fail_before_writes(self):
        targets = [self.host / 'usr/local/lib/qacey-dev', self.host / 'usr/local/bin/qacey-dev',
                   self.host / 'etc/qacey-dev', self.host / 'etc/systemd/system/qacey-openchamber.service']
        for target in targets:
            with self.subTest(target=target):
                target.symlink_to(self.host / 'missing')
                with self.assertRaises(ValueError): self.setup.main(['--apply'])
                self.assertFalse(self.record.exists())
                target.unlink()
        drop = self.host / 'etc/systemd/system/qacey-codex-tmux.service.d'
        drop.mkdir()
        with self.assertRaises(ValueError): self.setup.main(['--apply'])
        self.assertFalse(self.record.exists())

    def test_empty_record_does_not_establish_installation_ownership(self):
        self.record.parent.mkdir()
        for value in ({}, [], None):
            self.record.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.setup.main(['--apply'])
            self.assertFalse((self.host / 'usr/local/bin/qacey-dev').exists())

    def test_existing_secret_metadata_is_checked_without_reading_values(self):
        self.setup.main(['--apply'])
        secret = self.host / 'etc/qacey-dev/openchamber.env'
        secret.write_text('private operator value')
        secret.chmod(0o644)
        with self.assertRaises(ValueError): self.setup.main(['--apply'])
        secret.unlink()
        secret.symlink_to(self.home / 'other-secret')
        with self.assertRaises(ValueError): self.setup.main(['--apply'])

    def test_bad_port_node_and_foundation_identity_fail(self):
        for argv in (['--port','80'], ['--port','65536'], ['--node','relative'], ['--node','/tmp/../node']):
            with self.subTest(argv=argv), self.assertRaises(ValueError): self.setup.main([*argv,'--apply'])
        self.foundation_record['ready'] = False
        (self.host / 'etc/qacey-codex/installation.json').write_text(json.dumps(self.foundation_record))
        with self.assertRaises(ValueError): self.setup.main(['--apply'])
        self.assertFalse(self.record.exists())


if __name__ == '__main__': unittest.main()
