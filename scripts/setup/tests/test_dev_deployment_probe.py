"""Real disposable HTTP transport tests; no runtime, provider or host-service calls."""

import base64
from contextlib import redirect_stdout, redirect_stderr
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import urllib.parse


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('qacey_test_deployment_probe', ROOT / 'infrastructure/dev-agent/deployment_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
UI_PASSWORD = 'synthetic-ui-password-' + 'u' * 32
BACKEND_PASSWORD = 'synthetic-backend-password-' + 'b' * 32
BINARY = '/home/fixture/.local/share/qacey-dev/runtime/opencode-2.4.1/opencode'
DIRECTORY = '/home/fixture/projects/first'


class Reply:
    def __init__(self, payload=None, *, status=200, raw=None, headers=None, delay=0):
        self.payload, self.status, self.raw = payload, status, raw
        self.headers, self.delay = headers or {}, delay


class WireFixture:
    def __init__(self):
        self.seen, self.validations = [], []
        self.health = dict(status='ok', openchamberVersion='2.8.0', openCodeRunning=True,
                           isOpenCodeReady=True, openCodeSecureConnection=True, openCodeAuthSource='user-env',
                           opencodeBinaryResolved=BINARY, opencodeBinarySource='env')
        self.ui_routes = {
            '/api/terminal/sessions': {'sessions': []},
            '/api/openchamber/scheduled-tasks/status': dict(hasEnabledScheduledTasks=False,
                hasRunningScheduledTasks=False, enabledScheduledTasksCount=0, runningScheduledTasksCount=0),
            '/api/session-warming': {'revision': 1, 'enabled': False, 'minutes': 30, 'sessions': []},
            '/api/config/settings': {'projects': [{'path': DIRECTORY}]},
            '/api/message-queue': {'revision': 1, 'sessions': []},
            '/api/auto-review': {'revision': 1, 'runs': []},
            '/api/pr-watch': {'revision': 1, 'watches': []},
            '/api/extension-waits': {'revision': 1, 'waits': []},
            '/api/openchamber/workflows': {'runs': []},
        }
        self.backend_routes = {
            '/api/info': {'version': '2.4.1', 'pid': os.getpid()},
            '/api/session/active': {'data': {}},
            '/api/experimental/job': {'data': []},
            '/api/experimental/automation': {'data': []},
            '/api/debug/location': [{'directory': DIRECTORY}],
            '/api/config': [{'type': 'document', 'info': {'warming': False}}],
        }
        self.pages = {None: {'data': [], 'cursor': {}}}
        self.overrides = {}
        self.servers, self.threads = [], []
        for role in ('opencode', 'openchamber'):
            handler = self.handler(role)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            thread.start()
            self.servers.append(server); self.threads.append(thread)
        self.backend_port, self.port = [server.server_port for server in self.servers]
        self.health['openCodePort'] = self.backend_port

    def close(self):
        for server in self.servers:
            server.shutdown(); server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)

    def validator(self, port, role):
        self.validations.append((port, role))
        return (port, role) in ((self.port, 'openchamber'), (self.backend_port, 'opencode'))

    def arguments(self):
        return dict(port=self.port, expected_openchamber='2.8.0', expected_opencode='2.4.1',
                    expected_binary=BINARY, ui_password=UI_PASSWORD, backend_password=BACKEND_PASSWORD,
                    validate_listener=self.validator)

    def handler(self, role):
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                fixture.seen.append(dict(role=role, path=parsed.path, query=query, method=self.command,
                                         authorization=self.headers.get('Authorization'), cookie=self.headers.get('Cookie'), body=body))
                response = fixture.overrides.get((role, parsed.path))
                if response is None and role == 'opencode':
                    expected = 'Basic ' + base64.b64encode(('opencode:' + BACKEND_PASSWORD).encode()).decode()
                    if self.headers.get('Authorization') != expected:
                        response = Reply({'error': 'authentication required'}, status=401)
                    elif parsed.path == '/api/session':
                        response = fixture.pages.get(query.get('cursor', [None])[0], Reply({}, status=400))
                    else:
                        directory = query.get('location[directory]', [None])[0]
                        response = fixture.backend_routes.get((parsed.path, directory), fixture.backend_routes.get(parsed.path))
                        if response is None and parsed.path in ('/api/shell', '/api/pty', '/api/permission/request', '/api/form'):
                            response = {'location': {'directory': directory}, 'data': []}
                elif response is None and parsed.path == '/health':
                    response = fixture.health
                elif response is None and parsed.path == '/auth/session':
                    if self.command == 'POST':
                        if json.loads(body).get('password') == UI_PASSWORD:
                            response = Reply({'authenticated': True}, headers={'Set-Cookie': 'fixture=valid; Path=/; HttpOnly'})
                        else:
                            response = Reply({'authenticated': False}, status=401)
                    elif self.headers.get('Cookie') == 'fixture=valid':
                        response = {'authenticated': True}
                    else:
                        response = Reply({'authenticated': False}, status=401)
                elif response is None:
                    if self.headers.get('Cookie') != 'fixture=valid':
                        response = Reply({'error': 'authentication required'}, status=401)
                    else:
                        response = fixture.ui_routes.get(parsed.path)
                if response is None:
                    response = Reply({'error': 'unexpected fixture route'}, status=404)
                if not isinstance(response, Reply):
                    response = Reply(response)
                if response.delay:
                    time.sleep(response.delay)
                payload = response.raw if response.raw is not None else json.dumps(response.payload).encode()
                self.send_response(response.status)
                for key, value in {'Content-Type': 'application/json', 'Content-Length': str(len(payload)), **response.headers}.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return Handler


class DeploymentProbeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = WireFixture()
        self.addCleanup(self.fixture.close)

    def check(self, **kwargs):
        return probe.probe(**(self.fixture.arguments() | kwargs))

    def assert_unknown(self, **kwargs):
        result = self.check(**kwargs)
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual(set(result), {'state', 'reason'})
        return result

    def test_default_idle_uses_real_http_cookie_login_and_direct_backend(self):
        self.assertEqual(self.check(), {'state': 'idle', 'reason': 'idle'})
        self.assertEqual(len(self.fixture.validations), len(self.fixture.seen))
        self.assertTrue(any(item['path'] == '/api/session/active' and item['role'] == 'opencode' for item in self.fixture.seen))
        self.assertFalse(any(item['path'] == '/api/session/active' and item['role'] == 'openchamber' for item in self.fixture.seen))
        for request in self.fixture.seen:
            if request['role'] == 'opencode':
                self.assertIsNone(request['cookie'])
                self.assertTrue(request['authorization'].startswith('Basic '))
            else:
                self.assertIsNone(request['authorization'])
        mutations = [item for item in self.fixture.seen if item['method'] != 'GET']
        self.assertEqual([item['path'] for item in mutations], ['/auth/session'])
        self.assertEqual(set(json.loads(mutations[0]['body'])), {'password'})

    def test_health_only_allows_busy_service_and_does_not_inspect_activity(self):
        self.fixture.ui_routes['/api/terminal/sessions'] = {'sessions': [{'status': 'running'}]}
        self.assertEqual(self.check(health_only=True), {'state': 'healthy', 'reason': 'healthy'})
        self.assertEqual({item['path'] for item in self.fixture.seen}, {'/health', '/api/info', '/auth/session'})

    def test_owner_rejection_or_exception_sends_no_credentials_or_requests(self):
        for callback in (lambda *_: False, lambda *_: 1, lambda *_: (_ for _ in ()).throw(RuntimeError(UI_PASSWORD))):
            with self.subTest(callback=callback):
                result = self.assert_unknown(validate_listener=callback)
                self.assertEqual(result['reason'], 'listener_unverified')
                self.assertEqual(self.fixture.seen, [])

    def test_backend_ownership_is_checked_before_basic_credentials(self):
        result = self.assert_unknown(validate_listener=lambda port, role: role == 'openchamber')
        self.assertEqual(result['reason'], 'listener_unverified')
        self.assertEqual([item['path'] for item in self.fixture.seen], ['/health'])

    def test_ownership_is_rechecked_before_cookie_authenticated_requests(self):
        def validator(port, role):
            return len(self.fixture.seen) < 4
        self.assertEqual(self.assert_unknown(validate_listener=validator)['reason'], 'listener_unverified')
        self.assertEqual(len(self.fixture.seen), 4)
        self.assertFalse(any(item['path'] == '/api/terminal/sessions' for item in self.fixture.seen))

    def test_health_checks_exact_versions_binary_ready_auth_source_and_port(self):
        for key, value in (('openchamberVersion', 'wrong'), ('opencodeBinaryResolved', '/unmanaged'),
                           ('openCodeRunning', False), ('isOpenCodeReady', 1), ('openCodeSecureConnection', False),
                           ('openCodeAuthSource', 'shared-service'), ('opencodeBinarySource', 'external'),
                           ('openCodePort', True), ('openCodePort', self.fixture.port)):
            with self.subTest(key=key):
                original = self.fixture.health[key]
                self.fixture.health[key] = value
                self.assertEqual(self.assert_unknown()['reason'], 'health_mismatch')
                self.fixture.health[key] = original
        self.fixture.backend_routes['/api/info']['version'] = 'wrong'
        self.assertEqual(self.assert_unknown()['reason'], 'health_mismatch')

    def test_invalid_arguments_credentials_and_unreviewed_activity_versions_do_not_connect(self):
        for values in ({'port': True}, {'port': 80}, {'budget': float('inf')}, {'timeout': 0},
                       {'expected_binary': '/home/../unmanaged'}, {'ui_password': 'short'},
                       {'expected_opencode': '3.0.0'}):
            with self.subTest(values=values):
                self.assert_unknown(**values)
        self.assertEqual(self.fixture.seen, [])

    def test_foreground_hidden_sessions_background_jobs_and_browser_terminal_block(self):
        for role, path, payload, reason in (
            ('openchamber', '/api/terminal/sessions', {'sessions': [{'status': 'running'}]}, 'openchamber_terminals'),
            ('opencode', '/api/session/active', {'data': {'hidden-session': {'type': 'running'}}}, 'opencode_sessions'),
            ('opencode', '/api/experimental/job', {'data': [{'status': 'running', 'kind': 'shell'}]}, 'opencode_jobs'),
        ):
            with self.subTest(reason=reason):
                routes = self.fixture.ui_routes if role == 'openchamber' else self.fixture.backend_routes
                original = routes[path]; routes[path] = payload
                self.assertEqual(self.check(), {'state': 'busy', 'reason': reason})
                routes[path] = original

    def test_autonomous_producers_queues_and_waiting_work_block_between_agent_turns(self):
        cases = [
            ('/api/openchamber/scheduled-tasks/status', dict(hasEnabledScheduledTasks=True,
                hasRunningScheduledTasks=False, enabledScheduledTasksCount=1, runningScheduledTasksCount=0), 'scheduled_tasks'),
            ('/api/session-warming', {'enabled': True, 'sessions': []}, 'session_warming'),
            ('/api/config/settings', {'agentMemoryToolEnabled': True, 'agentMemoryDreamingEnabled': True}, 'memory_dreaming'),
            ('/api/message-queue', {'sessions': [{'items': [{'id': 'pending'}], 'sendingId': None}]}, 'message_queue'),
            ('/api/message-queue', {'sessions': [{'items': [], 'sendingId': 'sending'}]}, 'message_queue'),
            ('/api/auto-review', {'runs': [{'status': 'running'}]}, 'auto_review'),
            ('/api/pr-watch', {'watches': [{'status': 'waiting'}]}, 'pr_watch'),
            ('/api/extension-waits', {'waits': [{'status': 'waiting'}]}, 'extension_waits'),
            ('/api/openchamber/workflows', {'runs': [{'state': 'awaiting-approval'}]}, 'workflows'),
        ]
        for path, payload, reason in cases:
            with self.subTest(reason=reason):
                original = self.fixture.ui_routes[path]; self.fixture.ui_routes[path] = payload
                self.assertEqual(self.check(), {'state': 'busy', 'reason': reason})
                self.fixture.ui_routes[path] = original
        self.fixture.backend_routes['/api/experimental/automation'] = {'data': [{'status': 'active'}]}
        self.assertEqual(self.check(), {'state': 'busy', 'reason': 'opencode_automations'})

    def test_later_session_pages_preserve_active_goals_and_leads(self):
        self.fixture.pages[None] = {'data': [], 'cursor': {'next': 'next-page'}}
        session = {'id': 'session-later', 'location': {'directory': DIRECTORY}, 'metadata': {'openchamber': {'goal': {'status': 'active'}}}}
        self.fixture.pages['next-page'] = {'data': [session], 'cursor': {}}
        self.assertEqual(self.check(), {'state': 'busy', 'reason': 'session_goal'})
        session['metadata']['openchamber'] = {'lead': {'at': 1}}
        self.assertEqual(self.check(), {'state': 'busy', 'reason': 'session_lead'})
        session['metadata']['openchamber'] = {'goal': {'status': 'complete'}}
        self.assertEqual(self.check()['state'], 'idle')
        session['metadata']['openchamber'] = {'goal': {'status': 'unknown-new-state'}}
        self.assert_unknown()

    def test_location_scoped_shell_pty_forms_permissions_and_warming_are_checked(self):
        second = '/home/fixture/projects/second'
        self.fixture.backend_routes['/api/debug/location'].append({'directory': second})
        for route, payload, reason in (
            ('/api/shell', [{'status': 'running'}], 'opencode_shells'),
            ('/api/pty', [{'status': 'running'}], 'opencode_ptys'),
            ('/api/permission/request', [{'id': 'pending'}], 'opencode_pending_requests'),
            ('/api/form', [{'id': 'pending'}], 'opencode_pending_requests'),
        ):
            with self.subTest(route=route):
                self.fixture.backend_routes[(route, second)] = {'location': {'directory': second}, 'data': payload}
                self.assertEqual(self.check(), {'state': 'busy', 'reason': reason})
                del self.fixture.backend_routes[(route, second)]
        self.fixture.backend_routes[('/api/config', second)] = [{'type': 'document', 'info': {'warming': {}}}]
        self.assertEqual(self.check(), {'state': 'busy', 'reason': 'opencode_warming'})
        self.fixture.backend_routes[('/api/config', second)].append({'type': 'document', 'info': {'warming': False}})
        self.assertEqual(self.check()['state'], 'idle')

    def test_stored_projects_do_not_boot_unloaded_location_plugins(self):
        self.fixture.ui_routes['/api/config/settings']['projects'].append({'path': '/home/fixture/projects/old'})
        self.assertEqual(self.check()['state'], 'idle')
        scoped_backend = [item for item in self.fixture.seen if item['role'] == 'opencode' and 'location[directory]' in item['query']]
        self.assertTrue(all(item['query']['location[directory]'] == [DIRECTORY] for item in scoped_backend))

    def test_exited_terminals_and_completed_work_do_not_prevent_idle(self):
        self.fixture.ui_routes['/api/terminal/sessions'] = {'sessions': [{'status': 'exited'}]}
        self.fixture.backend_routes['/api/experimental/job'] = {'data': [{'status': 'completed'}]}
        self.fixture.backend_routes['/api/experimental/automation'] = {'data': [{'status': 'paused'}, {'status': 'done'}]}
        self.fixture.ui_routes['/api/auto-review'] = {'runs': [{'status': 'clean'}, {'status': 'stopped'}]}
        self.fixture.ui_routes['/api/openchamber/workflows'] = {'runs': [{'state': 'completed'}]}
        self.assertEqual(self.check()['state'], 'idle')

    def test_missing_or_malformed_activity_is_unknown_never_idle(self):
        for role, path, value in (
            ('opencode', '/api/session/active', []),
            ('opencode', '/api/session/active', {'data': []}),
            ('opencode', '/api/session/active', {'data': {'id': {'type': 'idle'}}}),
            ('opencode', '/api/experimental/job', {}),
            ('openchamber', '/api/terminal/sessions', {'sessions': [{'status': 'unknown'}]}),
            ('openchamber', '/api/openchamber/scheduled-tasks/status', {'hasEnabledScheduledTasks': False}),
            ('openchamber', '/api/message-queue', {'sessions': [{'items': None}]}),
        ):
            with self.subTest(path=path, value=value):
                routes = self.fixture.ui_routes if role == 'openchamber' else self.fixture.backend_routes
                original = routes[path]; routes[path] = value
                self.assert_unknown()
                routes[path] = original

    def test_redirect_is_not_followed_and_cookie_and_body_are_not_forwarded(self):
        self.fixture.overrides[('openchamber', '/auth/session')] = Reply({}, status=307,
            headers={'Location': f'http://127.0.0.1:{self.fixture.backend_port}/redirect-sink'})
        self.assertEqual(self.assert_unknown()['reason'], 'http_redirect')
        self.assertFalse(any(item['path'] == '/redirect-sink' for item in self.fixture.seen))

    def test_unauthenticated_ui_must_be_locked_and_failed_login_is_unknown(self):
        self.fixture.overrides[('openchamber', '/auth/session')] = {'authenticated': True}
        self.assert_unknown()
        self.fixture.overrides.clear()
        self.assert_unknown(ui_password='incorrect-synthetic-password-' + 'x' * 24)

    def test_untrusted_json_payload_headers_and_size_fail_closed(self):
        replies = [Reply(raw=b'{"sessions":[],"sessions":[]}'), Reply(raw=b'{"sessions":[],"extra":NaN}'),
                   Reply(raw=b'not-json'), Reply({'sessions': []}, headers={'Content-Type': 'text/html'}),
                   Reply({'sessions': []}, headers={'Content-Encoding': 'gzip'}),
                   Reply({'sessions': []}, headers={'Content-Length': str(probe.MAX_RESPONSE + 1)}),
                   Reply({'sessions': []}, status=503)]
        for reply in replies:
            with self.subTest(reply=reply):
                self.fixture.overrides[('openchamber', '/api/terminal/sessions')] = reply
                self.assert_unknown()

    def test_request_timeout_and_total_budget_are_bounded(self):
        self.fixture.overrides[('openchamber', '/health')] = Reply(self.fixture.health, delay=.2)
        start = time.monotonic()
        self.assert_unknown(timeout=.03, budget=.1)
        self.assertLess(time.monotonic() - start, .5)
        self.fixture.overrides.clear()
        self.assert_unknown(budget=.000001)

    def test_pagination_cycles_and_inspection_limits_fail_closed(self):
        self.fixture.pages = {None: {'data': [], 'cursor': {'next': 'cycle'}}, 'cycle': {'data': [], 'cursor': {'next': 'cycle'}}}
        self.assert_unknown()
        self.fixture.pages['cycle'] = {'data': [], 'cursor': {'next': 'third'}}
        with patch.object(probe, 'MAX_SESSION_PAGES', 2):
            self.assertEqual(self.assert_unknown()['reason'], 'inspection_limit')
        self.fixture.pages = {None: {'data': [], 'cursor': {}}}
        with patch.object(probe, 'MAX_LOCATIONS', 0):
            self.assertEqual(self.assert_unknown()['reason'], 'inspection_limit')
        with patch.object(probe, 'MAX_REQUESTS', 2):
            self.assertEqual(self.assert_unknown()['reason'], 'inspection_limit')

    def test_location_echo_must_match_and_path_must_be_canonical(self):
        self.fixture.backend_routes['/api/shell'] = {'location': {'directory': '/other'}, 'data': []}
        self.assert_unknown()
        del self.fixture.backend_routes['/api/shell']
        self.fixture.backend_routes['/api/debug/location'] = [{'directory': '/home/../other'}]
        self.assert_unknown()

    def test_errors_do_not_print_payloads_or_secrets_and_ignore_proxy_environment(self):
        self.fixture.overrides[('openchamber', '/api/terminal/sessions')] = Reply({'error': UI_PASSWORD + BACKEND_PASSWORD}, status=500)
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output), patch.dict(os.environ, {
            'HTTP_PROXY': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1',
            'ALL_PROXY': 'http://127.0.0.1:1', 'NO_PROXY': '', 'http_proxy': 'http://127.0.0.1:1'}):
            result = self.assert_unknown()
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn(UI_PASSWORD, str(result)); self.assertNotIn(BACKEND_PASSWORD, str(result))
        self.assertTrue(any(item['path'] == '/api/terminal/sessions' for item in self.fixture.seen))


if __name__ == '__main__':
    unittest.main()
