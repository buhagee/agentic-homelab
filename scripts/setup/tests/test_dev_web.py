"""Offline behavior tests for the separately activated development gateway."""
import base64
import importlib.util
import io
import grp
import pwd
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'infrastructure/dev-agent'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class WebTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ASSETS / 'web_config.py').exists(), 'missing gateway implementation')
        self.web = load('web_config', ASSETS / 'web_config.py')
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = dict(hostname='dev.example.test', issuer='https://id.example.test/realm',
                             client_id='development-client', emails=['owner@example.test'],
                             cert_resolver='letsencrypt', mfa_required=True)
        self.identity = dict(user='dev-agent', uid=1200, gid=1200, home='/home/dev-agent', port=3939)
        self.versions = {'OAUTH2_PROXY_VERSION': 'v7.15.6', 'CADDY_VERSION': '2.11.9-alpine'}

    def test_rejects_injection_in_host_issuer_email_and_resolver(self):
        invalid = {'hostname': ['localhost', '*.example.test', 'dev.example.test`)', '127.0.0.1', 'x/y.test', 'host.test\n'],
                   'issuer': ['http://id.example.test', 'https://user:pw@id.example.test', 'https://id.example.test?x=1', 'https://id.example.test/#x'],
                   'emails': [[], ['*'], ['*@example.test'], ['a@example.test,b@example.test']],
                   'cert_resolver': ['a b', 'a\nb', ''], 'mfa_required': [False],
                   'client_id': ['', 'client\n']}
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.web.validate_settings(dict(self.settings, **{key: value}))

    def test_render_has_no_unauthenticated_bypass_and_separate_project(self):
        files = self.web.render(self.settings, self.identity, self.versions, ASSETS / 'web')
        compose, oauth, caddy = (files[name].decode() for name in ('compose.yml', 'oauth2-proxy.cfg', 'Caddyfile'))
        self.assertIn('name: qacey-dev-web', compose)
        self.assertIn('format: raw', compose)
        self.assertIn('traefik.http.routers.qacey-dev.observability.accesslogs=false', compose)
        self.assertIn('exclude http.log.error', caddy)
        self.assertIn('internal: true', compose)
        self.assertIn('name: qacey-proxy', compose)
        self.assertIn('user: "1200:1200"', compose)
        self.assertIn('create_host_path: false', compose)
        self.assertNotIn('ports:', compose)
        self.assertNotIn('network_mode:', compose)
        self.assertNotIn('docker.sock', compose)
        self.assertNotIn('email_domains', oauth)
        self.assertNotIn('skip_auth_routes', oauth)
        self.assertNotIn('trusted_ips', oauth)
        self.assertIn('cookie_name = "__Host-qacey-dev"', oauth)
        self.assertIn('cookie_secure = true', oauth)
        self.assertIn('cookie_httponly = true', oauth)
        self.assertIn('pass_authorization_header = false', oauth)
        self.assertIn('pass_basic_auth = false', oauth)
        self.assertIn('X-Forwarded-Proto https', caddy)
        self.assertNotIn('header_up Authorization', caddy)
        self.assertIn('respond @wrongOrigin 403', caddy)
        self.assertIn('respond @noWsOrigin 403', caddy)
        self.assertIn('respond @noMutationOrigin 403', caddy)

    def test_oracle_route_overrides_only_the_development_hostname(self):
        files = self.web.render(self.settings, self.identity, self.versions, ASSETS / 'web')
        edge = files['oracle-dev-route.yml'].decode()
        self.assertIn('rule: "Host(`dev.example.test`)"', edge)
        self.assertNotIn('HostRegexp', edge)
        self.assertIn('priority: 150', edge)
        for line in ('entryPoints: [websecure]', 'certResolver: letsencrypt',
                     'middlewares: [secure-headers, qacey-dev-edge-marker]', 'service: home-server-svc',
                     'accessLogs: false', 'X-Qacey-Dev-Edge: "dev.example.test"'):
            self.assertIn(line, edge)
        self.assertNotIn('accessLog:', edge)

    def test_raw_secrets_preserve_dollars_and_quotes_without_shell_parsing(self):
        secret = self.directory / 'oauth2.env'
        secret.write_text('OAUTH2_PROXY_CLIENT_SECRET=abc$literal"quoted\'value\nOAUTH2_PROXY_COOKIE_SECRET=' + base64.b64encode(b'x' * 32).decode() + '\n')
        secret.chmod(0o600)
        values = self.web.secret_values(secret, 'oauth', owner=os.geteuid())
        self.assertEqual(values['OAUTH2_PROXY_CLIENT_SECRET'], 'abc$literal"quoted\'value')

    def test_secret_keys_modes_links_and_cookie_size_fail_closed(self):
        path = self.directory / 'secret'
        good = 'OAUTH2_PROXY_CLIENT_SECRET=fixture\nOAUTH2_PROXY_COOKIE_SECRET=' + base64.b64encode(b'x' * 32).decode() + '\n'
        for data in (good + 'OAUTH2_PROXY_EMAIL_DOMAINS=*\n', good + 'OAUTH2_PROXY_CLIENT_SECRET=again\n',
                     good.replace('fixture', ''), good.replace(base64.b64encode(b'x' * 32).decode(), 'short'),
                     good.replace(base64.b64encode(b'x' * 32).decode(), base64.b64encode(bytes([251]) * 32).decode())):
            path.write_text(data); path.chmod(0o600)
            with self.assertRaises(ValueError): self.web.secret_values(path, 'oauth', owner=os.geteuid())
        path.write_text(good); path.chmod(0o644)
        with self.assertRaises(ValueError): self.web.secret_values(path, 'oauth', owner=os.geteuid())
        path.chmod(0o600)
        link = self.directory / 'linked'; link.symlink_to(path)
        with self.assertRaises(ValueError): self.web.secret_values(link, 'oauth', owner=os.geteuid())
        hardlink = self.directory / 'hardlink'; os.link(path, hardlink)
        with self.assertRaises(ValueError): self.web.secret_values(path, 'oauth', owner=os.geteuid())

    def test_native_secrets_use_safe_systemd_subset_and_no_extra_overrides(self):
        path = self.directory / 'native'
        good = 'OPENCHAMBER_UI_PASSWORD=' + 'a' * 32 + '\nOPENCODE_PASSWORD=' + 'b' * 32 + '\n'
        path.write_text(good); path.chmod(0o600)
        self.assertEqual(len(self.web.secret_values(path, 'native', owner=os.geteuid())), 2)
        for data in (good + 'OPENCODE_JWT_SECRET=no\n', good.replace('a' * 32, 'short'),
                     good.replace('a' * 32, '"' + 'a' * 32 + '"'), good.replace('a' * 32, 'a' * 31 + '\\')):
            path.write_text(data)
            with self.assertRaises(ValueError): self.web.secret_values(path, 'native', owner=os.geteuid())

    def test_identity_checks_foundation_record_private_home_and_groups(self):
        uid, gid = os.geteuid(), os.getegid()
        home = self.directory / 'home/dev-agent'; home.mkdir(parents=True); home.chmod(0o700)
        record = dict(schema=1, ready=True, user='dev-agent', uid=uid, gid=gid, home=str(home), marker='fixture')
        for name in ('qacey-codex', 'qacey-dev'):
            directory = self.directory / 'etc' / name; directory.mkdir(parents=True)
            (directory / 'installation.json').write_text(json.dumps(record))
        account = pwd.struct_passwd(('dev-agent', 'x', uid, gid, 'fixture', str(home), '/bin/bash'))
        group = grp.struct_group(('dev-agent', 'x', gid, []))
        with patch.object(self.web, 'ROOT_UID', uid), patch.object(pwd, 'getpwnam', return_value=account), \
                patch.object(pwd, 'getpwall', return_value=[account]), patch.object(grp, 'getgrnam', return_value=group), \
                patch.object(os, 'getgrouplist', return_value=[gid]) as groups:
            self.assertEqual(self.web.development_record(self.directory)['uid'], uid)
            groups.return_value = [gid, gid + 1]
            with self.assertRaises(ValueError): self.web.development_record(self.directory)
            groups.return_value = [gid]
            home.chmod(0o755)
            with self.assertRaises(ValueError): self.web.development_record(self.directory)
            home.chmod(0o700)
            (self.directory / 'etc/qacey-dev/installation.json').write_text(json.dumps(dict(record, uid=uid + 1)))
            with self.assertRaises(ValueError): self.web.development_record(self.directory)

    def test_compose_version_floor_and_environment_are_explicit(self):
        for value in ('2.30.0', 'v2.35.1', '5.0.0'):
            self.web.check_compose_version(value)
        for value in ('2.29.9', '1.29.2', 'unknown'):
            with self.assertRaises(ValueError): self.web.check_compose_version(value)
        with patch.dict(os.environ, {'DOCKER_HOST': 'tcp://evil:2375', 'COMPOSE_PROJECT_NAME': 'production'}):
            command, environment = self.web.compose_command(self.directory)
        self.assertEqual(command[:3], ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock'])
        self.assertIn('qacey-dev-web', command)
        self.assertNotIn('DOCKER_HOST', environment)
        self.assertNotIn('COMPOSE_PROJECT_NAME', environment)


class WebProvisionTests(unittest.TestCase):
    def setUp(self):
        self.setup = load('test_install_dev_web', ROOT / 'scripts/setup/install-dev-web.py')
        self.web = self.setup.web
        self.host = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.host.chmod(0o755)
        for name in ('etc/qacey-dev', 'usr/local/lib', 'usr/local/bin'):
            (self.host / name).mkdir(parents=True, exist_ok=True)
        self.enterContext(patch.object(self.setup, 'HOST_ROOT', self.host))
        self.enterContext(patch.object(self.setup, 'ROOT_UID', os.geteuid()))
        self.enterContext(patch.object(self.setup, 'source_version', return_value='b' * 40))
        self.identity = dict(user='dev-agent', uid=1200, gid=1200, home='/home/dev-agent', port=3939)
        self.enterContext(patch.object(self.web, 'development_record', return_value=self.identity))
        self.settings = dict(hostname='dev.example.test', issuer='https://id.example.test/realm',
                             client_id='client', emails=['owner@example.test'],
                             cert_resolver='letsencrypt', mfa_required=True)
        self.settings_path = self.host / 'settings.json'
        self.settings_path.write_text(json.dumps(self.settings))
        self.output = self.enterContext(redirect_stdout(io.StringIO()))
        self.args = ['--settings', str(self.settings_path)]
        self.directory = self.host / 'etc/qacey-dev/web'
        self.calls = self.enterContext(patch.object(subprocess, 'run', side_effect=AssertionError('unexpected host command')))

    def test_dry_run_is_write_free_and_apply_installs_only_assets(self):
        before = sorted(self.host.rglob('*'))
        self.setup.main(self.args)
        self.assertEqual(sorted(self.host.rglob('*')), before)
        self.setup.main([*self.args, '--apply'])
        self.assertTrue(json.loads((self.directory / 'installation.json').read_text())['ready'])
        self.assertFalse((self.directory / 'oauth2.env').exists())
        self.assertFalse((self.directory.parent / 'openchamber.env').exists())
        self.assertTrue((self.host / 'usr/local/bin/qacey-dev-web').is_file())
        rule = self.host / 'etc/tmpfiles.d/qacey-dev-proxy.conf'
        self.assertEqual(rule.read_text(), 'd /run/qacey-dev-proxy 0755 root root -\n')
        self.assertFalse((self.host / 'run/qacey-dev-proxy').exists())
        self.calls.assert_not_called()
        with patch.object(os, 'geteuid', return_value=os.geteuid() + 1), self.assertRaises(PermissionError):
            self.setup.main([*self.args, '--apply'])

    def test_preexisting_identical_boot_rule_is_accepted_and_conflicting_rule_is_preserved(self):
        rule = self.host / 'etc/tmpfiles.d/qacey-dev-proxy.conf'
        rule.parent.mkdir()
        rule.write_bytes(self.setup.PROXY_TMPFILES)
        self.setup.main([*self.args, '--apply'])
        conflicting = 'd /run/qacey-dev-proxy 0777 root root -\n'
        rule.write_text(conflicting)
        with self.assertRaisesRegex(ValueError, 'Conflicting qacey-dev-proxy tmpfiles rule'):
            self.setup.main([*self.args, '--apply'])
        self.assertEqual(rule.read_text(), conflicting)

    def test_private_lock_created_only_by_apply_and_never_uses_directory_inode(self):
        lock = self.host / 'etc/qacey-dev/web.lock'
        self.setup.main(self.args)
        self.assertFalse(lock.exists())
        self.setup.main([*self.args, '--apply'])
        self.assertTrue(lock.is_file())
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        with self.web.gateway_lock(self.host) as descriptor:
            info = os.fstat(descriptor)
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(info.st_ino, lock.stat().st_ino)
            self.assertEqual(info.st_uid, os.geteuid())

    def test_unsafe_lock_metadata_is_rejected_before_any_gateway_write(self):
        lock = self.host / 'etc/qacey-dev/web.lock'
        lock.write_text(''); lock.chmod(0o644)
        with self.assertRaises(ValueError): self.setup.main([*self.args, '--apply'])
        self.assertFalse(self.directory.exists())
        lock.unlink(); lock.symlink_to(self.settings_path)
        with self.assertRaises(ValueError): self.setup.main([*self.args, '--apply'])
        lock.unlink(); lock.write_text(''); lock.chmod(0o600)
        sibling = lock.with_name('extra-link'); os.link(lock, sibling)
        with self.assertRaises(ValueError): self.setup.main([*self.args, '--apply'])
        sibling.unlink()
        from types import SimpleNamespace
        original = Path.lstat
        def wrong_owner(path):
            info = original(path)
            if path == lock:
                return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid + 1,
                                       st_nlink=info.st_nlink, st_size=info.st_size)
            return info
        with patch.object(Path, 'lstat', wrong_owner), self.assertRaises(ValueError):
            self.setup.main([*self.args, '--apply'])
        self.assertFalse(self.directory.exists())

    def test_unrelated_directory_or_helper_is_never_adopted(self):
        for path in (self.directory, self.host / 'usr/local/lib/qacey-dev-web'):
            path.mkdir()
            with self.assertRaises(ValueError): self.setup.main([*self.args, '--apply'])
            self.assertFalse((self.directory / 'installation.json').exists())
            path.rmdir()
        launcher = self.host / 'usr/local/bin/qacey-dev-web'
        launcher.symlink_to(self.host / 'missing')
        with self.assertRaises(ValueError): self.setup.main([*self.args, '--apply'])

    def test_rerun_preserves_secrets_and_refuses_managed_drift(self):
        self.setup.main([*self.args, '--apply'])
        secret = self.directory / 'oauth2.env'
        secret.write_text('operator secret is not parsed during preparation'); secret.chmod(0o600)
        self.setup.main([*self.args, '--apply'])
        self.assertEqual(secret.read_text(), 'operator secret is not parsed during preparation')
        target = self.directory / 'Caddyfile'
        target.write_text(target.read_text() + '# local edit\n')
        with self.assertRaises(ValueError): self.setup.main([*self.args, '--apply'])
        self.assertTrue(target.read_text().endswith('# local edit\n'))

    def test_previous_gateway_file_set_upgrades_without_adopting_a_collision(self):
        self.setup.main([*self.args, '--apply'])
        path = self.directory / 'installation.json'
        record = json.loads(path.read_text())
        record['files'].pop('oracle-dev-route.yml')
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'unrelated Oracle'):
            self.setup.main([*self.args, '--apply'])
        (self.directory / 'oracle-dev-route.yml').unlink()
        self.setup.main([*self.args, '--apply'])
        self.assertIn('oracle-dev-route.yml', json.loads(path.read_text())['files'])

    def verified_route(self):
        return json.loads((self.directory / 'installation.json').read_text())['files']['oracle-dev-route.yml']

    def test_interrupted_publication_can_finish_but_cannot_change_version(self):
        provision = self.setup.Provision(self.settings)
        original = self.setup.write_atomic
        def fail(path, data, mode=0o644):
            if path.name == 'Caddyfile': raise OSError('injected interruption')
            return original(path, data, mode)
        with patch.object(self.setup, 'write_atomic', side_effect=fail), self.assertRaises(OSError): provision.apply()
        self.assertFalse(json.loads((self.directory / 'installation.json').read_text())['ready'])
        with self.assertRaises(ValueError): self.setup.Provision(dict(self.settings, hostname='other.example.test')).apply()
        provision.apply()
        self.assertTrue(json.loads((self.directory / 'installation.json').read_text())['ready'])

    def lifecycle(self, *, active_units=()):
        self.setup.main([*self.args, '--apply'])
        entry = load('test_qacey_dev_web', ASSETS / 'qacey-dev-web.py')
        self.enterContext(patch.object(entry, 'HOST_ROOT', self.host))
        self.enterContext(patch.object(entry, 'ROOT_UID', os.geteuid()))
        commands = []
        def run(command):
            commands.append(command)
            if command[:3] == ['/usr/bin/systemctl', 'is-active', '--quiet']:
                units = command[3:]
                # A grouped systemctl check succeeds if any requested unit is active.
                if not any(unit in active_units for unit in units):
                    raise RuntimeError(f'Inactive native units: {", ".join(units)}')
            return '2.30.0' if 'version' in command else ''
        self.enterContext(patch.object(entry, 'run', side_effect=run))
        return entry, commands

    def credentials(self):
        oauth = self.directory / 'oauth2.env'
        oauth.write_text('OAUTH2_PROXY_CLIENT_SECRET=not-a-live-secret\nOAUTH2_PROXY_COOKIE_SECRET=' + base64.b64encode(b'x' * 32).decode() + '\n')
        oauth.chmod(0o600)
        native = self.directory.parent / 'openchamber.env'
        native.write_text('OPENCHAMBER_UI_PASSWORD=' + 'a' * 32 + '\nOPENCODE_PASSWORD=' + 'b' * 32 + '\n')
        native.chmod(0o600)

    def test_check_refuses_missing_or_override_secrets_before_docker(self):
        entry, commands = self.lifecycle()
        with self.assertRaises(FileNotFoundError): entry.main(['check'])
        self.assertEqual(commands, [])
        self.credentials()
        with (self.directory / 'oauth2.env').open('a') as stream: stream.write('OAUTH2_PROXY_SKIP_AUTH_ROUTES=.*\n')
        with self.assertRaises(ValueError): entry.main(['check'])
        self.assertEqual(commands, [])

    def test_check_uses_quiet_config_and_start_requires_private_socket(self):
        entry, commands = self.lifecycle(); self.credentials()
        entry.main(['check'])
        self.assertIn(['config', '--quiet'], [command[-2:] for command in commands])
        self.assertFalse(any('up' in command for command in commands))
        with self.assertRaises(FileNotFoundError): entry.main(['start', '--verified-oracle-route', self.verified_route()])
        self.assertFalse(any('up' in command for command in commands))
        self.assertNotIn('not-a-live-secret', self.output.getvalue())

    def private_backend_socket(self):
        socket_path = self.host / 'run/qacey-dev-proxy/backend.sock'
        socket_path.parent.mkdir(parents=True)
        socket_info = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1200, st_gid=1200)
        real_lstat = Path.lstat

        def lstat(path):
            return socket_info if path == socket_path else real_lstat(path)

        self.enterContext(patch.object(Path, 'lstat', lstat))

    def test_updater_restores_gateway_with_managed_tmux_stopped(self):
        active_units = {'qacey-openchamber.service'}
        entry, commands = self.lifecycle(active_units=active_units)
        self.credentials()
        self.private_backend_socket()
        import deployment as core
        from deployment_host import Host

        def run(command, stage, **kwargs):
            if command == ['/usr/bin/systemctl', 'start', 'qacey-dev-proxy.socket']:
                active_units.add('qacey-dev-proxy.socket')
            elif command[0] == '/usr/local/bin/qacey-dev-web':
                entry.main(command[1:])
            else:
                self.fail(f'Unexpected updater command at {stage}: {command}')

        original = {'units': {'qacey-dev-proxy.socket': {'active': True},
                              'qacey-dev-proxy.service': {'active': False},
                              'qacey-codex-tmux.service': {'active': False}},
                    'gateway_active': True}
        with (patch.object(core, 'HOST_ROOT', self.host),
              patch.object(core, 'ROOT_UID', os.geteuid()),
              patch.object(core, 'run', side_effect=run)):
            host = Host(dict(self.identity, verified_oracle_route=self.verified_route()))
            host.restore_ingress(original)
        self.assertEqual(commands[-1][-3:], ['up', '-d', '--force-recreate'])

    def test_start_rejects_inactive_app_even_when_socket_is_active(self):
        entry, commands = self.lifecycle(active_units={'qacey-dev-proxy.socket', 'qacey-codex-tmux.service'})
        self.credentials()
        self.private_backend_socket()
        with self.assertRaisesRegex(RuntimeError, r'Inactive native units: qacey-openchamber\.service$'):
            entry.main(['start', '--verified-oracle-route', self.verified_route()])
        self.assertFalse(any('up' in command for command in commands))

    def test_start_rejects_inactive_socket_even_when_app_is_active(self):
        entry, commands = self.lifecycle(active_units={'qacey-openchamber.service', 'qacey-codex-tmux.service'})
        self.credentials()
        self.private_backend_socket()
        with self.assertRaisesRegex(RuntimeError, r'Inactive native units: qacey-dev-proxy\.socket$'):
            entry.main(['start', '--verified-oracle-route', self.verified_route()])
        self.assertFalse(any('up' in command for command in commands))

    def test_start_requires_attestation_for_current_hostname_and_fragment_before_docker(self):
        entry, commands = self.lifecycle()
        self.credentials()
        old = self.verified_route()
        self.setup.Provision(dict(self.settings, hostname='other.example.test')).apply()
        for flags in ([], ['--verified-oracle-route', old], ['--verified-oracle-route', 'confirmed']):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'Verify the installed Oracle route'):
                entry.main(['start', *flags])
        self.assertEqual(commands, [])

    def test_explicit_start_recreates_containers_to_load_replaced_bind_files(self):
        entry, commands = self.lifecycle()
        compose, _ = self.web.compose_command(self.directory)
        with patch.object(entry, 'check', return_value=compose) as check:
            entry.main(['start', '--verified-oracle-route', self.verified_route()])
        check.assert_called_once_with(require_socket=True, verified_oracle_route=self.verified_route())
        self.assertEqual(commands[-1][-3:], ['up', '-d', '--force-recreate'])

    def test_stop_revokes_by_fixed_project_even_with_broken_config(self):
        entry, commands = self.lifecycle()
        (self.directory / 'compose.yml').unlink()
        calls = []
        def run(command):
            calls.append(command)
            return 'abcdef012345\n' if 'ls' in command else ''
        with patch.object(entry, 'run', side_effect=run): entry.main(['stop'])
        self.assertIn('label=com.docker.compose.project=qacey-dev-web', calls[0])
        self.assertEqual(calls[1][-4:], ['stop', '--time', '10', 'abcdef012345'])
        self.assertFalse(any('systemctl' in command for command in calls))


class GatewayFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load('test_gateway_fixture', ROOT / 'scripts/testing/check-dev-web.py')
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_caddy_fixture_environment_is_private_and_complete(self):
        with patch.dict(os.environ, {'HOME': '/persistent/home', 'XDG_CONFIG_HOME': '/persistent/config',
                                     'XDG_DATA_HOME': '/persistent/data', 'CADDY_UNKNOWN': 'inherited'}):
            env = self.fixture.fixture_environment(self.directory)
        for name in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'TMPDIR', 'TMP', 'TEMP'):
            path = Path(env[name])
            self.assertTrue(path.is_relative_to(self.directory))
            self.assertTrue(path.is_dir())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertNotIn('CADDY_UNKNOWN', env)

    def test_transport_releases_backend_after_port_or_adaptation_failure(self):
        for failure in ('bind', 'adapt'):
            with self.subTest(failure=failure), patch.object(self.fixture, 'UnixHTTP') as backend, \
                    patch.object(self.fixture.threading, 'Thread'), patch.object(self.fixture.socket, 'socket') as tcp, \
                    patch.object(self.fixture, 'transport_config', side_effect=ValueError('adapt failed')) as adapt:
                if failure == 'bind':
                    tcp.return_value.__enter__.return_value.bind.side_effect = OSError('bind failed')
                with self.assertRaises((OSError, ValueError)):
                    self.fixture.transport(None, self.directory, '', {})
                backend.return_value.shutdown.assert_called_once()
                backend.return_value.server_close.assert_called_once()
                self.assertEqual(adapt.called, failure == 'adapt')

    def test_adapted_transport_rejects_public_listeners_and_implicit_host_routes(self):
        port = 48888
        backend = self.directory / 'backend.sock'
        good = {'apps': {'http': {'servers': {'srv0': {'listen': ['127.0.0.1:48888'], 'routes': [
            {'match': [{'not': [{'host': ['dev.example.test']}]}],
             'handle': [{'handler': 'static_response', 'status_code': 421}]},
            {'handle': [{'handler': 'reverse_proxy', 'upstreams': [{'dial': 'unix/' + str(backend)}]}]}
        ]}}}}}
        self.fixture.check_adapted_transport(good, port, backend)
        import copy
        public = copy.deepcopy(good)
        public['apps']['http']['servers']['srv0']['listen'] = [':48888']
        with self.assertRaises(AssertionError): self.fixture.check_adapted_transport(public, port, backend)
        implicit = copy.deepcopy(good)
        implicit['apps']['http']['servers']['srv0']['routes'][1]['match'] = [{'host': ['127.0.0.1']}]
        with self.assertRaises(AssertionError): self.fixture.check_adapted_transport(implicit, port, backend)


if __name__ == '__main__': unittest.main()
