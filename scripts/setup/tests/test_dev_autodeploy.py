"""Native updater boundaries; all host/service/process/network state is isolated."""
import copy
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr, nullcontext
from types import SimpleNamespace
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'infrastructure/dev-agent'
sys.path.insert(0, str(ASSETS))
import deployment as core
from deployment_host import Host
import deployment_host

A = 'a' * 40
B = 'b' * 40


def policy():
    return dict(schema=1, operator='operator', repository=core.DEFAULT_REPOSITORY, branch='main',
                user='dev-agent', uid=1001, gid=1001, home='/home/dev-agent', port=3939,
                node='/usr/bin/node', verified_oracle_route='c' * 64,
                gateway=dict(hostname='dev.example.com', issuer='https://login.example.com',
                             client_id='native', emails=['owner@example.com'], cert_resolver='letsencrypt',
                             mfa_required=True))


def lifecycle(active=True):
    units = {name: dict(active=active, sub='running' if active else 'dead', enabled='disabled',
                        pid=43 if name == core.APP and active else 0,
                        start='1234' if active else '0', cgroup='/system.slice/' + name)
             for name in core.UNITS}
    units[core.CODEX]['active'] = False
    return dict(units=units, gateway_active=active,
                containers={'oauth': '1' * 64, 'adapter': '2' * 64} if active else {})


class FakeSource:
    def __init__(self, tree):
        self.tree, self.calls, self.tip = tree, [], A

    def fetch(self, revision):
        self.calls.append(('fetch', revision))
        if revision != self.tip:
            raise core.Blocked('requested-revision-is-not-current-main')

    def descendant(self, previous, revision):
        self.calls.append(('descendant', previous, revision))

    def checkout(self, revision, *, recovery=False):
        self.calls.append(('checkout', revision, recovery))
        return self.tree


class FakeHost:
    def __init__(self, active=True):
        self.current = lifecycle(active)
        self.calls = []
        self.observations = []
        self.fail = None
        self.secret_digest = dict(native='e' * 64, oauth='f' * 64)

    def check_records(self, **kwargs): self.calls.append(('records', kwargs))
    def credentials(self): return dict(self.secret_digest)
    def verify_managed(self, expected): self.calls.append(('managed', expected))
    def preflight(self, source): self.calls.append(('preflight',))
    def snapshot(self, **kwargs): return copy.deepcopy(self.current)
    def activity(self, snapshot, **kwargs):
        self.calls.append(('activity',))
        return self.observations.pop(0) if self.observations else dict(state='idle', reason='idle')
    def process_identity(self, snapshot):
        app = snapshot['units'][core.APP]
        return ['boot', app['active'], app['pid'], app['start']]
    def close_ingress(self, original):
        self.calls.append(('close',))
        for name in (core.SOCKET, core.PROXY): self.current['units'][name]['active'] = False
        self.current['gateway_active'] = False
    def restore_ingress(self, original):
        self.calls.append(('restore-ingress', copy.deepcopy(original)))
        for name in (core.SOCKET, core.PROXY):
            self.current['units'][name]['active'] = original['units'][name]['active']
        self.current['gateway_active'] = original['gateway_active']
    def stop_app(self, current):
        self.calls.append(('stop-app', current['units'][core.APP]['active']))
        self.current['units'][core.APP]['active'] = False
        self.current['units'][core.SOCKET]['active'] = False
    def publish(self, source):
        self.calls.append(('publish',))
        if self.fail == 'publish': raise core.Blocked('publish-failed')
    def install_runtime_and_sync(self): self.calls.append(('runtime-user-and-sync',))
    def reload_units(self): self.calls.append(('reload',))
    def restore_app(self, original):
        self.calls.append(('restore-app', original['units'][core.APP]['active']))
        self.current['units'][core.APP]['active'] = original['units'][core.APP]['active']
    def health(self, original):
        self.calls.append(('health',))
        if self.fail == 'health': raise core.Blocked('application-health-not-ready-fix-forward-required')
    def verify_restored(self, original): self.calls.append(('verify-restored',))
    def managed_files(self): return {'installed': '0' * 64}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.root.chmod(0o755)
        self.enterContext(patch.object(core, 'HOST_ROOT', self.root))
        self.enterContext(patch.object(core, 'ROOT_UID', os.geteuid()))
        for path in ('etc/qacey-dev', 'etc/sudoers.d', 'usr/local/sbin', 'usr/local/lib', 'var/lib'):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        self.p = policy()

    def enrolled(self):
        (self.root / core.STATE).mkdir(mode=0o700)
        core.save(self.root / core.POLICY, self.p)
        core.save(self.root / core.STATE / 'state.json', core.empty_state())

    def source_tree(self):
        tree = self.root / 'candidate' / A
        for relative in set(core.INPUTS):
            path = tree / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, path)
        (tree / 'versions.env').write_text('OAUTH2_PROXY_VERSION=v7.8.1\nCADDY_VERSION=2.9.1-alpine\nOTHER=old\n')
        return tree


class PolicyAndBoundaryTests(Fixture):
    def test_delegated_apply_requires_exact_argv_before_opening_policy(self):
        with patch.object(core, 'load_policy', side_effect=AssertionError('policy opened')):
            for args in ([], ['--', A], [A, 'extra'], ['--help'], [A + '\n'], ['pause']):
                with self.subTest(args=args), self.assertRaisesRegex(core.Blocked, 'invalid-revision'):
                    core.main(['apply', *args])

    def test_missing_opt_in_is_noop_without_lock_state_or_sources(self):
        before = sorted(self.root.rglob('*'))
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(core.main(['apply', A]), 0)
        self.assertIn('not-enrolled', output.getvalue())
        self.assertEqual(sorted(self.root.rglob('*')), before)

    def test_argument_identity_repository_and_environment_boundaries(self):
        for revision in ('A' * 40, 'a' * 39, 'a' * 41, A + '\n', '--help', '../' + A):
            with self.subTest(revision=revision), self.assertRaises((core.Blocked, SystemExit)):
                core.main(['apply', revision])
        with patch.object(os, 'geteuid', return_value=core.ROOT_UID + 1), self.assertRaises(core.Blocked):
            core.main(['apply', A])
        for url in ('file:///tmp/source', 'ssh://github.com/x/y', 'https://user:secret@github.com/x/y',
                    'https://github.com/x/y?token=secret', 'https://github.com.evil/x/y', 'https://github.com:443/x/y'):
            with self.subTest(url=url), self.assertRaises(core.Blocked): core.repository(url)
        self.assertEqual(core.repository(core.DEFAULT_REPOSITORY), core.DEFAULT_REPOSITORY)

    def test_present_invalid_policy_fails_closed(self):
        self.enrolled()
        path = self.root / core.POLICY
        path.chmod(0o644)
        with self.assertRaises(core.Blocked): core.load_policy()
        path.chmod(0o600)
        for key, value in (('uid', 0), ('operator', 'dev-agent'), ('branch', 'release'), ('port', 80)):
            value_policy = dict(self.p, **{key: value})
            core.save(path, value_policy)
            with self.subTest(key=key), self.assertRaises(core.Blocked): core.load_policy()
        path.unlink()
        path.symlink_to(self.root / 'missing')
        with self.assertRaises(core.Blocked): core.load_policy()

    def test_permanent_private_nonblocking_lock(self):
        self.enrolled()
        path = self.root / core.STATE / 'deployment.lock'
        with core.deployment_lock():
            before = path.stat()
            self.assertEqual(stat.S_IMODE(before.st_mode), 0o600)
            with self.assertRaisesRegex(core.Blocked, 'another-native'):
                with core.deployment_lock(): pass
        with core.deployment_lock(): self.assertTrue(os.path.samestat(before, path.stat()))
        path.unlink()
        path.symlink_to(self.root / core.STATE / 'state.json')
        with self.assertRaises(core.Blocked):
            with core.deployment_lock(): pass

    def test_root_user_commands_capture_output_and_drop_inherited_settings(self):
        malicious = dict(GIT_CONFIG_COUNT='9', DOCKER_HOST='tcp://bad', PYTHONPATH='/bad', LD_PRELOAD='/bad', HOME='/bad')
        with patch.dict(os.environ, malicious), patch.object(subprocess, 'Popen') as child, patch.object(os, 'killpg'):
            process = Mock(returncode=1, pid=123)
            process.communicate.return_value = ('synthetic-secret', 'synthetic-secret')
            child.return_value = process
            with self.assertRaisesRegex(core.Blocked, '^runtime-failed$'):
                core.run(['/fixed/runtime'], 'runtime', identity=self.p)
            kwargs = child.call_args.kwargs
            self.assertEqual((kwargs['user'], kwargs['group'], kwargs['extra_groups']), (1001, 1001, []))
            self.assertEqual(kwargs['env']['HOME'], '/home/dev-agent')
            self.assertEqual(kwargs['cwd'], '/home/dev-agent')
            self.assertFalse(set(malicious) - {'HOME'} & kwargs['env'].keys())
            self.assertEqual((kwargs['stdout'], kwargs['stderr']), (subprocess.PIPE, subprocess.PIPE))
            self.assertTrue(kwargs['start_new_session'])
            self.assertEqual(kwargs['umask'], 0o077)
            process.returncode = 0
            core.run(['/fixed/root-step'], 'root-step')
            self.assertEqual(child.call_args.kwargs['env'], core.SYSTEM_ENV)
            self.assertNotIn('user', child.call_args.kwargs)

    def test_timeout_terminates_spawned_writer_before_releasing_control(self):
        marker = self.root / 'late-writer'
        writer = 'import pathlib,time; time.sleep(0.3); pathlib.Path(' + repr(str(marker)) + ').write_text("unexpected")'
        command = ('import subprocess,time,sys; subprocess.Popen([sys.executable,"-c",' + repr(writer) + ']); '
                   'time.sleep(3)')
        with self.assertRaisesRegex(core.Blocked, '^isolated-timeout-failed$'):
            core.run([sys.executable, '-I', '-c', command], 'isolated-timeout', timeout=0.05)
        time.sleep(0.4)
        self.assertFalse(marker.exists())

    def test_pause_resume_preserve_transaction_under_same_lock(self):
        self.enrolled()
        state = core.load_state()
        transaction = dict(revision=A, digest='d' * 64, phase='starting', original=lifecycle(),
                           credentials=dict(native='e' * 64, oauth='f' * 64))
        state['transaction'] = transaction
        core.save(self.root / core.STATE / 'state.json', state)
        with redirect_stdout(io.StringIO()):
            core.main(['pause'])
            paused = core.load_state()
            self.assertTrue(paused['paused'])
            self.assertEqual(paused['transaction'], transaction)
            inode = (self.root / core.STATE / 'deployment.lock').stat()
            core.main(['resume'])
        resumed = core.load_state()
        self.assertFalse(resumed['paused'])
        self.assertEqual(resumed['transaction'], transaction)
        self.assertTrue(os.path.samestat(inode, (self.root / core.STATE / 'deployment.lock').stat()))

    def test_fingerprint_excludes_docs_and_unrelated_versions(self):
        source = self.source_tree()
        first = core.fingerprint(source, self.p)
        (source / 'README.md').write_text('unrelated docs')
        versions = source / 'versions.env'
        versions.write_text(versions.read_text().replace('OTHER=old', 'OTHER=new'))
        self.assertEqual(core.fingerprint(source, self.p), first)
        versions.write_text(versions.read_text().replace('v7.8.1', 'v7.8.2'))
        self.assertNotEqual(core.fingerprint(source, self.p), first)
        self.assertNotEqual(core.fingerprint(source, dict(self.p, port=4949)), core.fingerprint(source, self.p))

    def test_worker_only_change_does_not_request_application_restart(self):
        source = self.source_tree()
        before = core.fingerprint(source, self.p)
        worker = source / 'infrastructure/dev-agent/deployment_probe.py'
        worker.write_text(worker.read_text() + '\n# reviewed worker update\n')
        self.assertEqual(core.fingerprint(source, self.p), before)


class LifecycleTests(Fixture):
    def setUp(self):
        super().setUp()
        self.enrolled()
        self.tree = self.source_tree()
        self.host, self.source = FakeHost(), FakeSource(self.tree)
        self.now = 1000
        self.enterContext(patch.object(core, 'refresh_updater', side_effect=lambda source: self.host.calls.append(('refresh',))))

    def apply(self, revision=A):
        controller = core.Deployment(self.p, self.host, self.source, clock=lambda: self.now)
        result = controller.apply(revision)
        return result, controller.state

    def quiet(self):
        result, state = self.apply()
        self.assertEqual(result, 0)
        self.assertEqual(state['reason'], 'quiet-observation-required')
        self.now += 61

    def test_two_idle_observations_no_blocking_sleep_and_original_proxy_retained(self):
        self.quiet()
        self.assertNotIn(('close',), self.host.calls)
        _, state = self.apply()
        self.assertEqual(state['status'], 'applied')
        self.assertEqual(state['applied_revision'], A)
        restored = next(c[1] for c in self.host.calls if c[0] == 'restore-ingress')
        self.assertTrue(restored['units'][core.PROXY]['active'])
        self.assertTrue(self.host.current['units'][core.PROXY]['active'])
        self.assertTrue(self.host.current['units'][core.TMUX]['active'])

    def test_busy_unknown_and_process_identity_changes_reset_quiet(self):
        self.quiet()
        self.host.observations = [dict(state='busy', reason='tmux-session-active')]
        _, state = self.apply()
        self.assertEqual(state['status'], 'pending')
        self.assertIsNone(state['quiet'])
        self.quiet()
        self.host.observations = [dict(state='unknown', reason='listener_unverified')]
        _, state = self.apply()
        self.assertIsNone(state['quiet'])
        self.quiet()
        self.host.current['units'][core.APP]['pid'] += 1
        _, state = self.apply()
        self.assertEqual(state['reason'], 'quiet-observation-required')
        self.assertNotIn(('publish',), self.host.calls)

    def test_changed_helper_yields_to_next_invocation_before_touching_application(self):
        with patch.object(core, 'refresh_updater', return_value=True) as refresh:
            _, state = self.apply()
        refresh.assert_called_once_with(self.tree)
        self.assertEqual(state['reason'], 'helper-refreshed')
        self.assertIsNone(state['transaction'])
        self.assertIsNone(state['applied_revision'])
        self.assertFalse(self.host.calls)

    def test_active_journal_does_not_switch_helper(self):
        self.quiet()
        self.host.fail = 'publish'
        with self.assertRaises(core.Blocked):
            self.apply()
        self.host.fail = None
        with patch.object(core, 'refresh_updater', side_effect=AssertionError('journal switched helper')):
            _, state = self.apply()
        self.assertEqual(state['status'], 'applied')

    def test_status_names_failed_stage_but_never_copies_unexpected_error_text(self):
        for exc, reason in ((core.Blocked('gateway-inspection-failed'), 'gateway-inspection-failed'),
                            (ValueError('private child output'), 'fix-forward-or-local-review-required')):
            with self.subTest(reason=reason), patch.object(self.host, 'snapshot', side_effect=exc):
                with self.assertRaises(type(exc)):
                    self.apply()
                self.assertEqual(core.load_state()['reason'], reason)

    def test_post_ingress_activity_race_restores_only_original_ingress(self):
        self.quiet()
        self.host.observations = [dict(state='idle', reason='idle'), dict(state='busy', reason='message_queue')]
        _, state = self.apply()
        self.assertEqual(state['reason'], 'message_queue')
        self.assertIsNone(state['transaction'])
        self.assertTrue(self.host.current['gateway_active'])
        self.assertNotIn(('publish',), self.host.calls)
        self.assertFalse(any(c[0] == 'stop-app' for c in self.host.calls))

    def test_final_fresh_activity_race_restores_ingress_before_any_publication(self):
        self.quiet()
        self.host.observations = [dict(state='idle', reason='idle'), dict(state='idle', reason='idle'),
                                  dict(state='unknown', reason='opencode_pending_requests')]
        _, state = self.apply()
        self.assertEqual(state['reason'], 'opencode_pending_requests')
        self.assertIsNone(state['transaction'])
        self.assertTrue(self.host.current['gateway_active'])
        self.assertFalse(any(c[0] in ('stop-app', 'publish') for c in self.host.calls))

    def test_stopped_and_disabled_components_remain_stopped(self):
        self.host = FakeHost(active=False)
        self.quiet()
        _, state = self.apply()
        self.assertEqual(state['status'], 'applied')
        self.assertFalse(self.host.current['gateway_active'])
        self.assertTrue(all(not u['active'] and u['enabled'] == 'disabled' for u in self.host.current['units'].values()))
        self.assertIn(('stop-app', False), self.host.calls)

    def test_unchanged_digest_does_not_reinstall_or_claim_drift_repair(self):
        self.quiet()
        self.apply()
        self.host.calls.clear()
        self.source.tip = B
        _, state = self.apply(B)
        self.assertEqual(state['desired_revision'], B)
        self.assertEqual(state['applied_revision'], A)
        self.assertEqual(state['reason'], 'inputs-unchanged-no-repair-attempted')
        self.assertFalse(any(c[0] in ('publish', 'close', 'preflight') for c in self.host.calls))

    def test_failed_publication_keeps_original_journal_and_recovers_same_verified_source(self):
        self.quiet()
        self.host.fail = 'publish'
        with self.assertRaises(core.Blocked): self.apply()
        pending = core.load_state()['transaction']
        self.assertEqual(pending['phase'], 'publishing')
        self.assertTrue(pending['original']['units'][core.APP]['active'])
        self.assertFalse(self.host.current['gateway_active'])
        self.source.tip = B
        self.source.calls.clear()
        self.host.fail = None
        _, state = self.apply(A)
        self.assertEqual(state['status'], 'applied')
        self.assertIn(('checkout', A, True), self.source.calls)
        self.assertFalse(any(c[0] == 'fetch' for c in self.source.calls))
        self.assertTrue(self.host.current['units'][core.APP]['active'])
        self.assertTrue(self.host.current['gateway_active'])

    def test_failed_new_start_health_retries_forward_without_runtime_rollback_or_republication(self):
        self.quiet()
        self.host.fail = 'health'
        with self.assertRaises(core.Blocked): self.apply()
        self.assertEqual(core.load_state()['transaction']['phase'], 'starting')
        self.assertFalse(self.host.current['gateway_active'])
        self.host.calls.clear()
        self.host.fail = None
        _, state = self.apply()
        self.assertEqual(state['status'], 'applied')
        self.assertNotIn(('publish',), self.host.calls)
        self.assertNotIn(('runtime-user-and-sync',), self.host.calls)
        self.assertFalse(any(c[0] == 'stop-app' for c in self.host.calls))

    def test_interrupted_credential_drift_is_blocked_and_original_journal_preserved(self):
        self.quiet()
        self.host.fail = 'publish'
        with self.assertRaises(core.Blocked): self.apply()
        journal = core.load_state()['transaction']
        self.host.secret_digest['native'] = '9' * 64
        with self.assertRaisesRegex(core.Blocked, 'credentials-changed'):
            self.apply()
        self.assertEqual(core.load_state()['transaction'], journal)
        self.assertFalse(self.host.current['gateway_active'])

    def test_paused_apply_has_no_source_or_host_mutation(self):
        state = core.load_state()
        state['paused'] = True
        core.save(self.root / core.STATE / 'state.json', state)
        _, state = self.apply()
        self.assertEqual(state['reason'], 'operator-paused')
        self.assertEqual(self.host.calls, [])
        self.assertEqual(self.source.calls, [])


class HostBoundaryTests(Fixture):
    def setUp(self):
        super().setUp()
        self.host = Host.__new__(Host)
        self.host.root, self.host.policy = self.root, self.p
        self.host.web = core.load_module('test_native_web', ASSETS / 'web_config.py')
        self.host.web.ROOT_UID = core.ROOT_UID
        self.host.records = None
        self.host.native_secrets = None

    def test_missing_private_or_linked_credentials_rejected_without_creation(self):
        directory = self.root / 'etc/qacey-dev/web'
        directory.mkdir()
        native = directory.parent / 'openchamber.env'
        oauth = directory / 'oauth2.env'
        with self.assertRaises(core.Blocked): self.host.credentials()
        native.write_text('OPENCHAMBER_UI_PASSWORD=' + 'a' * 32 + '\nOPENCODE_PASSWORD=' + 'b' * 32 + '\n')
        oauth.write_text('OAUTH2_PROXY_CLIENT_SECRET=synthetic-secret\nOAUTH2_PROXY_COOKIE_SECRET=' + 'YWFh' * 8 + '\n')
        for path in (native, oauth): path.chmod(0o600)
        values = self.host.credentials()
        self.assertEqual(set(values), {'native', 'oauth'})
        before = native.read_bytes()
        native.chmod(0o644)
        with self.assertRaises(core.Blocked): self.host.credentials()
        self.assertEqual(native.read_bytes(), before)
        native.unlink()
        native.symlink_to(oauth)
        with self.assertRaises(core.Blocked): self.host.credentials()

    def test_oracle_route_change_blocks_before_stop_or_provision(self):
        source = self.source_tree()
        with patch.object(core, 'run') as child, self.assertRaisesRegex(core.Blocked, 'oracle-route-changed'):
            self.host.preflight(source)
        child.assert_not_called()

    def test_detached_tmux_sessions_are_busy_and_runtime_runs_as_existing_identity(self):
        (self.root / 'proc').mkdir()
        snapshot = lifecycle()
        with patch.object(core, 'run', return_value=subprocess.CompletedProcess([], 0, '$0\n', '')) as child:
            result = self.host.user_process_activity(snapshot)
            self.assertEqual(result, dict(state='busy', reason='tmux-session-active'))
            self.assertIn('list-sessions', child.call_args.args[0])
            self.assertEqual(child.call_args.kwargs['identity'], self.p)
            child.reset_mock()
            self.host.install_runtime_and_sync()
            self.assertEqual([call.args[0] for call in child.call_args_list], [
                ['/usr/local/bin/qacey-dev', 'install-runtime', '--apply'],
                ['/usr/local/bin/qacey-dev', 'sync', '--apply'],
            ])
            self.assertTrue(all(c.kwargs['identity'] == self.p for c in child.call_args_list))

    def test_managed_codex_process_is_busy_even_without_tmux(self):
        process = self.root / 'proc/901'
        process.mkdir(parents=True)
        (process / 'status').write_text('Name:\tcodex\nUid:\t1001\t1001\t1001\t1001\n')
        (process / 'exe').symlink_to('/home/dev-agent/.codex/runtime/codex')
        (process / 'cmdline').write_bytes(b'codex\0')
        result = self.host.user_process_activity(lifecycle(False))
        self.assertEqual(result['reason'], 'codex-process-active')

    def test_foreground_native_clients_defer_even_when_managed_app_is_stopped(self):
        process = self.root / 'proc/902'
        process.mkdir(parents=True)
        (process / 'status').write_text('Uid:\t1001\t1001\t1001\t1001\n')
        (process / 'cgroup').write_text('0::/user.slice/foreground.scope\n')
        executable = process / 'exe'
        executable.symlink_to('/usr/bin/node')
        (process / 'cmdline').write_bytes(b'node\0/home/dev-agent/.local/share/qacey-dev/runtime/openchamber-2.8.0-node24/build/bin/cli.js\0serve\0--foreground\0')
        stopped = lifecycle(False)
        self.assertEqual(self.host.user_process_activity(stopped)['reason'], 'foreground-native-client-active')
        executable.unlink()
        executable.symlink_to('/home/dev-agent/.local/share/qacey-dev/runtime/opencode-2.4.0/opencode')
        (process / 'cmdline').write_bytes(b'opencode\0serve\0')
        self.assertEqual(self.host.user_process_activity(stopped)['state'], 'busy')
        (process / 'cgroup').write_text('0::/system.slice/qacey-openchamber.service\n')
        running = lifecycle()
        running['units'][core.TMUX]['active'] = False
        self.assertEqual(self.host.user_process_activity(running)['state'], 'idle')
        with patch.object(self.host, 'probe', return_value=dict(state='busy', reason='opencode_sessions')) as probe:
            self.assertEqual(self.host.activity(running)['reason'], 'opencode_sessions')
            probe.assert_called_once()

    def test_socket_inspection_does_not_require_service_only_properties(self):
        output = ('LoadState=loaded\nActiveState=active\nSubState=listening\nUnitFileState=disabled\n'
                  'FragmentPath=/etc/systemd/system/qacey-dev-proxy.socket\nDropInPaths=\n')
        with patch.object(core, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            actual = self.host.unit(core.SOCKET)
        self.assertTrue(actual['active'])
        self.assertEqual(actual['pid'], 0)

    def test_application_startup_waits_for_delayed_readiness_and_has_deadline(self):
        now = [0.0]
        def sleep(seconds): now[0] += seconds
        with patch.object(self.host, 'check_records'), patch.object(self.host, 'credentials'), \
             patch.object(core, 'run'), \
             patch.object(deployment_host.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(deployment_host.time, 'sleep', side_effect=sleep), \
             patch.object(self.host, 'probe', side_effect=[dict(state='unknown', reason='health_mismatch'),
                                                         dict(state='healthy', reason='healthy')]) as probe:
            self.host.health(lifecycle())
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(now[0], 1.0)
        now[0] = 0.0
        with patch.object(self.host, 'check_records'), patch.object(self.host, 'credentials'), \
             patch.object(core, 'run'), \
             patch.object(deployment_host.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(deployment_host.time, 'sleep', side_effect=sleep), \
             patch.object(self.host, 'probe', return_value=dict(state='unknown', reason='health_mismatch')):
            with self.assertRaisesRegex(core.Blocked, 'application-health-not-ready'):
                self.host.health(lifecycle())
            self.assertEqual(now[0], 60.0)

    def test_gateway_startup_waits_without_activating_backend_proxy(self):
        now = [0.0]
        seen = []
        class Opener:
            def open(self, request, **kwargs):
                seen.append(request)
                if len(seen) == 1: raise OSError('synthetic secret that must stay local')
                return nullcontext(SimpleNamespace(status=200 if ':4180/' in request.full_url else 421))
        containers = {
            'oauth': dict(running=True, image='quay.io/oauth2-proxy/oauth2-proxy:v7.8.1',
                          networks={'private': {'IPAddress': '172.20.0.2'}}),
            'adapter': dict(running=True, image='caddy:2.9.1-alpine',
                            networks={'private': {'IPAddress': '172.20.0.3'}}),
        }
        with patch.object(self.host.web, 'read_versions', return_value={'OAUTH2_PROXY_VERSION':'v7.8.1', 'CADDY_VERSION':'2.9.1-alpine'}), \
             patch.object(deployment_host, 'build_opener', return_value=Opener()), \
             patch.object(deployment_host.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(deployment_host.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            self.host.gateway_readiness(containers)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(request.headers['Host'] == 'qacey-deploy-readiness.invalid' for request in seen))
        self.assertTrue(all('Authorization' not in request.headers for request in seen))

    def test_no_lifecycle_command_can_touch_tmux_or_enablement(self):
        with patch.object(core, 'run') as child:
            for action, unit in (('stop', core.TMUX), ('start', core.TMUX), ('enable', core.APP), ('disable', core.SOCKET)):
                with self.subTest(action=action, unit=unit), self.assertRaises(core.Blocked): self.host.systemctl(action, unit)
            child.assert_not_called()

    def test_snapshot_allows_active_gateway_when_tmux_is_stopped(self):
        current = lifecycle()
        current['units'][core.TMUX]['active'] = False
        containers = {
            'oauth': dict(id='1' * 64, running=True),
            'adapter': dict(id='2' * 64, running=True),
        }
        with patch.object(self.host, 'unit', side_effect=lambda name: current['units'][name]), \
             patch.object(self.host, 'containers', return_value=containers):
            snap = self.host.snapshot()
        self.assertTrue(snap['gateway_active'])
        self.assertFalse(snap['units'][core.TMUX]['active'])

    def test_listener_requires_loopback_uid_and_actual_service_cgroup(self):
        net = self.root / 'proc/net'
        net.mkdir(parents=True)
        (net / 'tcp6').write_text('header\n')
        (net / 'tcp').write_text('header\n 0: 0100007F:0F63 00000000:0000 0A 0:0 0:0 0 1001 0 12345\n')
        process = self.root / 'proc/43'
        (process / 'fd').mkdir(parents=True)
        (process / 'fd/3').symlink_to('socket:[12345]')
        (process / 'status').write_text('Uid:\t1001\t1001\t1001\t1001\n')
        cgroup = process / 'cgroup'
        cgroup.write_text('0::/system.slice/qacey-openchamber.service\n')
        current = lifecycle()['units'][core.APP]
        with patch.object(self.host, 'unit', return_value=current):
            self.assertTrue(self.host.listener_owned(3939, 'openchamber'))
            cgroup.write_text('0::/user.slice/unrelated.service\n')
            self.assertFalse(self.host.listener_owned(3939, 'openchamber'))
            cgroup.write_text('0::/system.slice/qacey-openchamber.service\n')
            (net / 'tcp').write_text((net / 'tcp').read_text().replace('0100007F', '00000000'))
            self.assertFalse(self.host.listener_owned(3939, 'openchamber'))
            self.assertFalse(self.host.listener_owned(3939, 'arbitrary-role'))


class GitSourceTests(Fixture):
    def command(self, *args):
        return subprocess.run(['/usr/bin/git', *args], env=dict(core.GIT_ENV, GIT_AUTHOR_NAME='Fixture',
                              GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_NAME='Fixture',
                              GIT_COMMITTER_EMAIL='fixture@example.invalid'), capture_output=True, text=True, check=True).stdout.strip()

    def test_independent_root_source_tip_ancestry_and_integrity_with_real_git(self):
        self.enrolled()
        remote = self.source_tree()
        self.command('init', '--initial-branch=main', str(remote))
        self.command('-C', str(remote), 'add', '.')
        self.command('-C', str(remote), 'commit', '-m', 'first')
        first = self.command('-C', str(remote), 'rev-parse', 'HEAD')
        (remote / 'README.md').write_text('unrelated')
        self.command('-C', str(remote), 'add', '.')
        self.command('-C', str(remote), 'commit', '-m', 'second')
        second = self.command('-C', str(remote), 'rev-parse', 'HEAD')
        source = core.Source(self.p)
        original = source.git
        seen = []
        def isolated(args, **kwargs):
            seen.append(args)
            if self.p['repository'] in args:
                args = [str(remote) if arg == self.p['repository'] else arg for arg in args]
                kwargs['local'] = True  # Test-only transport adapter: no network request.
            return original(args, **kwargs)
        with patch.object(source, 'git', side_effect=isolated):
            with self.assertRaisesRegex(core.Blocked, 'not-current-main'): source.fetch(first)
            source.fetch(second)
            source.descendant(first, second)
            with self.assertRaisesRegex(core.Blocked, 'non-forward'): source.descendant(second, first)
            checkout = source.checkout(second)
            self.assertNotEqual(checkout, remote)
            self.assertEqual(self.command('-C', str(checkout), 'rev-parse', 'HEAD'), second)
            self.assertTrue((checkout / '.git').is_dir())
            self.assertEqual(source.checkout(second, recovery=True), checkout)
            (checkout / 'infrastructure/dev-agent/deployment.py').write_text('drift')
            with self.assertRaisesRegex(core.Blocked, 'revision-or-files-changed'): source.checkout(second, recovery=True)
        self.assertTrue(any(self.p['repository'] in args for args in seen))
        self.assertIn('GIT_CONFIG_NOSYSTEM', core.GIT_ENV)
        self.assertIn('core.hooksPath=/dev/null', core.GIT)
        self.assertIn('protocol.allow=never', core.GIT)

    def test_failed_initial_checkout_fetch_does_not_poison_immutable_target(self):
        self.enrolled()
        remote = self.source_tree()
        self.command('init', '--initial-branch=main', str(remote))
        self.command('-C', str(remote), 'add', '.')
        self.command('-C', str(remote), 'commit', '-m', 'fixture')
        revision = self.command('-C', str(remote), 'rev-parse', 'HEAD')
        source = core.Source(self.p)
        original = source.git
        fail = [True]
        def isolated(args, **kwargs):
            if self.p['repository'] in args:
                args = [str(remote) if arg == self.p['repository'] else arg for arg in args]
                kwargs['local'] = True
            elif 'fetch' in args and fail[0]:
                fail[0] = False
                raise core.Blocked('trusted-source-failed')
            return original(args, **kwargs)
        with patch.object(source, 'git', side_effect=isolated):
            source.fetch(revision)
            with self.assertRaises(core.Blocked): source.checkout(revision)
            self.assertFalse((self.root / core.STATE / 'sources' / revision).exists())
            self.assertEqual(source.checkout(revision).name, revision)


class BootstrapTests(Fixture):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location('test_install_dev_autodeploy', ROOT / 'scripts/setup/install-dev-autodeploy.py')
        self.bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bootstrap)
        self.bootstrap.core = core
        sys.modules['deployment'] = core

    def test_preview_is_read_only_and_requires_explicit_operator_and_edge_digest(self):
        before = sorted(self.root.rglob('*'))
        host = FakeHost()
        with patch.object(self.bootstrap, 'proposed', return_value=(self.p, host)), redirect_stdout(io.StringIO()):
            self.assertEqual(self.bootstrap.main(['--operator', 'operator', '--verified-oracle-route', 'c' * 64]), 0)
        self.assertEqual(sorted(self.root.rglob('*')), before)
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()): self.bootstrap.main([])

    def test_repair_existing_enrollment_keeps_policy_state_and_drift_baseline(self):
        self.enrolled()
        source = FakeSource(self.source_tree())
        shutil.copyfile(ASSETS / 'updater-compat.json', source.tree / 'infrastructure/dev-agent/updater-compat.json')
        (self.root / core.LIBRARY).mkdir()
        state_path = self.root / core.STATE / 'state.json'
        policy_path = self.root / core.POLICY
        state = core.load_state()
        state.update(managed_files={'existing': 'recorded'}, paused=True)
        core.save(state_path, state)
        before = (state_path.read_bytes(), policy_path.read_bytes())
        with patch.object(core, 'Source', return_value=source), patch.object(self.bootstrap, 'validate_rule'):
            self.bootstrap.repair(A)
        self.assertEqual(before, (state_path.read_bytes(), policy_path.read_bytes()))
        self.assertEqual(source.calls, [('fetch', A), ('descendant', None, A), ('checkout', A, False)])
        self.assertIn(' apply *', (self.root / 'etc/sudoers.d/qacey-dev-deploy').read_text())
        self.assertTrue((self.root / 'usr/local/sbin/qacey-dev-deploy').is_file())
        state['transaction'] = dict(revision=A, digest='b' * 64, phase='starting',
                                    original=lifecycle(), credentials={})
        core.save(state_path, state)
        with patch.object(core, 'Source', side_effect=AssertionError('opened source with journal')):
            with self.assertRaisesRegex(core.Blocked, 'transaction'):
                self.bootstrap.repair(A)

    def test_generated_policy_parses_with_installed_sudo_implementations(self):
        parsers = {path.resolve() for path in map(Path, (
            '/usr/sbin/visudo', '/usr/sbin/visudo.ws', '/usr/lib/cargo/bin/visudo')) if path.is_file()}
        if not parsers:
            self.skipTest('visudo not installed')
        for parser in sorted(parsers):
            with self.subTest(parser=parser):
                result = subprocess.run([str(parser), '-c', '-f', '-'], text=True,
                                        input=self.bootstrap.sudoers(self.p), capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_apply_installs_strict_sudo_rule_private_policy_and_retains_pause_on_reenrol(self):
        with patch.object(core, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as child:
            self.bootstrap.apply(self.p, FakeHost(), None)
            self.assertEqual(child.call_args.args[0], ['/usr/sbin/visudo', '-c', '-f', '-'])
        self.assertEqual(stat.S_IMODE((self.root / core.POLICY).stat().st_mode), 0o600)
        rule = (self.root / 'etc/sudoers.d/qacey-dev-deploy').read_text()
        self.assertIn('operator ALL=(root) NOPASSWD: NOSETENV:', rule)
        self.assertEqual(rule.splitlines()[-1], 'operator ALL=(root) NOPASSWD: NOSETENV: '
                         '/usr/local/sbin/qacey-dev-deploy apply *')
        self.assertNotIn('pause', rule)
        self.assertNotIn('dev-agent ALL', rule)
        state = core.load_state()
        state['paused'] = True
        core.save(self.root / core.STATE / 'state.json', state)
        inode = (self.root / core.STATE / 'deployment.lock').stat()
        with patch.object(core, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.bootstrap.apply(self.p, FakeHost(), self.p)
        self.assertTrue(core.load_state()['paused'])
        self.assertTrue(os.path.samestat(inode, (self.root / core.STATE / 'deployment.lock').stat()))

    def test_explicit_reviewed_checkout_import_does_not_require_root_owned_source(self):
        with patch.object(core, 'ROOT_UID', os.geteuid() + 1), patch.object(core, 'load_module') as forbidden:
            web = self.bootstrap.bootstrap_web()
            self.assertEqual(web.validate_settings(self.p['gateway']), self.p['gateway'])
        forbidden.assert_not_called()

    def test_sudoers_failure_is_readonly_and_interrupted_bootstrap_is_retryable(self):
        before = sorted(self.root.rglob('*'))
        with patch.object(core, 'run', side_effect=core.Blocked('sudoers-validation-failed')):
            with self.assertRaises(core.Blocked): self.bootstrap.apply(self.p, FakeHost(), None)
        self.assertEqual(sorted(self.root.rglob('*')), before)
        self.assertIsNone(self.bootstrap.preflight_destinations())
        with patch.object(core, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
             patch.object(core, 'install_updater_assets', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): self.bootstrap.apply(self.p, FakeHost(), None)
        self.assertIsNone(self.bootstrap.preflight_destinations())
        with patch.object(core, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.bootstrap.apply(self.p, FakeHost(), None)
        self.assertEqual(core.load_policy(), self.p)
        self.assertFalse((self.root / core.STATE / 'enrollment.json').exists())

    def test_helper_refresh_publishes_complete_version_before_launcher_switch(self):
        library = self.root / core.LIBRARY
        library.mkdir()
        core.install_updater_assets(ASSETS, trusted_source=False)
        launcher = self.root / 'usr/local/sbin/qacey-dev-deploy'
        before = launcher.read_bytes()
        next_assets = self.root / 'new-updater'
        next_assets.mkdir()
        for name in (*core.UPDATER_FILES, 'qacey-dev-deploy'):
            shutil.copyfile(ASSETS / name, next_assets / name)
        (next_assets / 'deployment.py').write_text((next_assets / 'deployment.py').read_text() + '\n# next reviewed version\n')
        atomic = core.atomic
        def interrupted(path, data, mode=0o600):
            if path.name == 'deployment_host.py': raise OSError('interrupted')
            return atomic(path, data, mode)
        with patch.object(core, 'atomic', side_effect=interrupted), self.assertRaises(OSError):
            core.install_updater_assets(next_assets)
        self.assertEqual(launcher.read_bytes(), before)
        core.install_updater_assets(next_assets)
        self.assertNotEqual(launcher.read_bytes(), before)
        target = launcher.read_text().splitlines()[1].split()[4]
        self.assertTrue((self.root / target.lstrip('/')).is_file())

    def test_incompatible_worker_cannot_replace_launcher(self):
        (self.root / core.LIBRARY).mkdir()
        source = self.source_tree()
        assets = source / 'infrastructure/dev-agent'
        compat = assets / 'updater-compat.json'
        shutil.copyfile(ASSETS / compat.name, compat)
        self.assertTrue(core.refresh_updater(source))
        launcher = self.root / 'usr/local/sbin/qacey-dev-deploy'
        before = launcher.stat()
        self.assertFalse(core.refresh_updater(source))
        compat.write_text('{"launcher":1,"policy":1,"state":2}')
        with self.assertRaisesRegex(core.Blocked, 'incompatible-helper'):
            core.refresh_updater(source)
        self.assertTrue(os.path.samestat(before, launcher.stat()))


if __name__ == '__main__':
    unittest.main()
