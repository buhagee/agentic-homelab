import configparser
import fcntl
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

    def test_bridge_stops_on_app_loss_and_request_cannot_start_prerequisites(self):
        self.setup.main(['--apply'])
        unit_dir = self.host / 'etc/systemd/system'

        def unit(name):
            result = configparser.ConfigParser(interpolation=None)
            result.read(unit_dir / name)
            return result

        app = 'qacey-openchamber.service'
        socket = 'qacey-dev-proxy.socket'
        bridge = unit(socket)
        # BindsTo + After closes the socket on intentional stop and unexpected app loss.
        self.assertEqual(bridge['Unit']['BindsTo'], app)
        self.assertIn(app, bridge['Unit']['After'].split())
        self.assertEqual(bridge['Socket']['RemoveOnStop'], 'true')
        # Operator recovery starts a late socket after a normally initialized service.
        self.assertEqual(bridge['Unit']['DefaultDependencies'], 'no')
        self.assertEqual(bridge['Unit']['Requires'], 'sysinit.target')
        self.assertIn('sysinit.target', bridge['Unit']['After'].split())
        self.assertEqual(bridge['Unit']['Before'], 'shutdown.target')
        self.assertEqual(bridge['Unit']['Conflicts'], 'shutdown.target')
        self.assertEqual(bridge['Install']['WantedBy'], 'multi-user.target')
        # The socket's stop job also terminates a previously activated proxyd.
        forwarder = unit('qacey-dev-proxy.service')['Unit']
        self.assertEqual(forwarder['PartOf'], socket)
        self.assertEqual(set(forwarder['Requisite'].split()), {app, socket})
        self.assertEqual(set(forwarder['After'].split()), {app, socket})
        for pulls_in_start in ('Wants', 'Requires', 'BindsTo', 'Upholds'):
            self.assertNotIn(pulls_in_start, forwarder)
        self.assertNotIn('Sockets', unit('qacey-dev-proxy.service')['Service'])
        tmux = (unit_dir / 'qacey-codex-tmux.service').read_text()
        self.assertNotIn(app, tmux)
        self.assertNotIn('qacey-dev-proxy', tmux)

    def test_policy_preserves_unrelated_values_and_rejects_conflicting_binary(self):
        directory = self.host / 'etc/openchamber'
        directory.mkdir()
        directory.chmod(0o755)
        policy = directory / 'policy.json'
        policy.write_text('{"someExistingPolicy": true}')
        policy.chmod(0o644)
        self.setup.main(['--apply'])
        data = json.loads(policy.read_text())
        self.assertTrue(data['someExistingPolicy'])
        self.assertNotEqual(data.get('enterpriseMode'), True)
        expected_opencode = json.loads((ASSETS / 'release.json').read_text())['opencode']['version']
        self.assertEqual(data['opencodeBinary'], str(self.home / f'.local/share/qacey-dev/runtime/opencode-{expected_opencode}/opencode'))
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

    def test_omitted_options_preserve_recorded_port_and_node(self):
        self.setup.main(['--port', '4949', '--node', '/opt/node/bin/node', '--apply'])
        with redirect_stdout(io.StringIO()) as output:
            self.setup.main([])
        self.assertIn('127.0.0.1:4949', output.getvalue())
        self.assertIn('/opt/node/bin/node', output.getvalue())
        for args, port, node in (([], 4949, '/opt/node/bin/node'),
                                 (['--port', '5999'], 5999, '/opt/node/bin/node'),
                                 (['--node', '/opt/next/bin/node'], 5999, '/opt/next/bin/node')):
            self.setup.main([*args, '--apply'])
            record = json.loads(self.record.read_text())
            self.assertEqual((record['port'], record['node']), (port, node))
            proxy = self.host / 'etc/systemd/system/qacey-dev-proxy.service'
            self.assertIn(f'127.0.0.1:{port}', proxy.read_text())

    def test_restrictive_umask_creates_traversable_policy_only_for_new_directory(self):
        directory = self.host / 'etc/openchamber'
        directory.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'policy directory'):
            self.setup.main(['--apply'])
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        directory.rmdir()
        before = os.umask(0o077)
        try:
            self.setup.main(['--apply'])
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)
            self.setup.main(['--apply'])
        finally:
            os.umask(before)

    def test_policy_directory_is_traversable_even_if_interrupted_at_mkdir(self):
        directory = self.host / 'etc/openchamber'
        mkdir = Path.mkdir
        original_umask = os.umask(0o077)
        try:
            for timing in ('before', 'after'):
                def interrupt(path, *args, **kwargs):
                    if path == directory and timing == 'before':
                        raise OSError('interrupted before mkdir')
                    mkdir(path, *args, **kwargs)
                    if path == directory and timing == 'after':
                        raise OSError('interrupted after mkdir')

                with self.subTest(timing=timing), patch.object(Path, 'mkdir', interrupt):
                    with self.assertRaisesRegex(OSError, 'interrupted'):
                        self.setup.main(['--apply'])
                    self.assertEqual(os.umask(0o077), 0o077)
                    self.assertFalse(json.loads(self.record.read_text())['ready'])
                    self.assertEqual(directory.exists(), timing == 'after')
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)
            self.assertFalse((directory / 'policy.json').exists())
            self.setup.main(['--apply'])
            self.assertTrue((directory / 'policy.json').is_file())
            self.assertTrue(json.loads(self.record.read_text())['ready'])
            self.assertEqual(os.umask(0o077), 0o077)
        finally:
            os.umask(original_umask)

    def test_interrupted_upgrade_retries_only_recorded_before_or_after_policy(self):
        self.setup.main(['--apply'])
        policy = self.host / 'etc/openchamber/policy.json'
        target = json.loads(policy.read_text())['opencodeBinary']
        expected_opencode = json.loads((ASSETS / 'release.json').read_text())['opencode']['version']
        old = target.replace(f'opencode-{expected_opencode}/', 'opencode-2.4.0/')
        write = self.setup.foundation.write_atomic
        for when in ('before', 'after'):
            with self.subTest(when=when):
                record = json.loads(self.record.read_text())
                record['opencode_version'] = '2.4.0'
                self.record.write_text(json.dumps(record))
                policy.write_text(json.dumps({'opencodeBinary': old, 'other': True}))

                def interrupt(path, data, mode):
                    if path == policy and when == 'before':
                        raise OSError('interrupted')
                    write(path, data, mode)
                    if path == policy and when == 'after':
                        raise OSError('interrupted')

                with patch.object(self.setup.foundation, 'write_atomic', side_effect=interrupt), self.assertRaises(OSError):
                    self.setup.main(['--apply'])
                pending = self.record.read_bytes()
                self.assertFalse(json.loads(pending)['ready'])
                actual = policy.read_bytes()
                self.assertEqual(json.loads(actual)['opencodeBinary'], old if when == 'before' else target)
                for drift in ({'opencodeBinary': '/unrelated/tool'}, {}):
                    policy.write_text(json.dumps(drift))
                    with self.assertRaisesRegex(ValueError, 'different OpenCode binary'):
                        self.setup.main(['--apply'])
                    self.assertEqual(self.record.read_bytes(), pending)
                policy.write_bytes(actual)
                self.setup.main(['--apply'])
                self.assertTrue(json.loads(self.record.read_text())['ready'])
                self.assertEqual(json.loads(policy.read_text()), {'opencodeBinary': target, 'other': True})

    def test_native_and_foundation_share_a_permanent_private_provision_lock(self):
        lock = self.host / 'etc/qacey-dev-provision.lock'
        self.setup.main([])
        self.assertFalse(lock.exists())
        self.setup.main(['--apply'])
        info = lock.stat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode)), (self.uid, 0o600))
        with lock.open('rb') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for install in (lambda: self.setup.main(['--apply']),
                            lambda: self.setup.foundation.Provision('dev-agent', self.home).apply()):
                with self.assertRaisesRegex(ValueError, 'Another native provisioner'):
                    install()
        self.setup.main(['--apply'])
        self.assertTrue(os.path.samestat(info, lock.stat()))
        lock.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private root-owned provisioning lock'):
            self.setup.main(['--apply'])
        lock.unlink()
        lock.symlink_to(self.record)
        with self.assertRaises(ValueError):
            self.setup.main(['--apply'])

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
