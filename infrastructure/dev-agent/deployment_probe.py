"""Bounded, read-only maintenance probes for the reviewed native runtime.

The caller owns lifecycle, quiet intervals, tmux checks and independent listener
ownership validation. These HTTP snapshots are not an atomic admission barrier.
OpenChamber's auxiliary recap/suggestion requests may be cancelled by its normal
shutdown. No provider request, user preference change or persistent client token
is made here; the UI login cookie is kept only in memory.
"""

import base64
import http.cookiejar
import json
import math
from pathlib import Path, PurePosixPath
import time
import urllib.error
import urllib.parse
import urllib.request


def _supported_activity_versions():
    versions = {('2.8.0', '2.4.1')}
    release_path = Path(__file__).with_name('release.json')
    try:
        release = json.loads(release_path.read_text(encoding='utf-8'))
        oc = release.get('openchamber', {}).get('version')
        op = release.get('opencode', {}).get('version')
        if isinstance(oc, str) and isinstance(op, str):
            versions.add((oc, op))
    except Exception:
        pass
    return versions


ACTIVITY_VERSIONS = _supported_activity_versions()
MAX_RESPONSE = 2 * 1024 * 1024
MAX_REQUESTS = 256
MAX_LOCATIONS = 32
MAX_SESSION_PAGES = 20
MAX_ITEMS = 2000


class _Failure(Exception):
    """The argument is always a fixed, nonsecret reason from this module."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        raise _Failure('http_redirect')


def _object(value):
    if not isinstance(value, dict):
        raise _Failure('invalid_response')
    return value


def _array(value):
    if not isinstance(value, list):
        raise _Failure('invalid_response')
    if len(value) > MAX_ITEMS:
        raise _Failure('inspection_limit')
    return value


def _text(value):
    if (not isinstance(value, str) or not value or len(value) > 16384
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise _Failure('invalid_response')
    return value


def _boolean(value):
    if type(value) is not bool:
        raise _Failure('invalid_response')
    return value


def _directory(value):
    value = _text(value)
    path = PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts or str(path) != value:
        raise _Failure('invalid_response')
    return value


def _data(value):
    value = _object(value)
    if 'data' not in value:
        raise _Failure('invalid_response')
    return value['data']


def _rows(value, key, statuses=None):
    rows = _array(_object(value).get(key))
    for item in rows:
        _object(item)
        if statuses is not None and item.get('status') not in statuses:
            raise _Failure('invalid_response')
    return rows


def _json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _Failure('invalid_response')
            result[key] = value
        return result

    def constant(_):
        raise _Failure('invalid_response')

    try:
        return json.loads(payload.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError):
        raise _Failure('invalid_response') from None


class _HTTP:
    def __init__(self, port, password, validate_listener, timeout, budget):
        self.port = port
        self.backend_port = None
        self.validate_listener = validate_listener
        self.timeout = timeout
        self.deadline = time.monotonic() + budget
        self.requests = 0
        self.authorization = 'Basic ' + base64.b64encode(('opencode:' + password).encode()).decode()
        self.public = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.ui = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
                                            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Failure('budget_exceeded')
        return min(self.timeout, remaining)

    def request(self, path, *, backend=False, authenticated=True, body=None, expected_status=200):
        self.requests += 1
        if self.requests > MAX_REQUESTS:
            raise _Failure('inspection_limit')
        self.remaining()
        port = self.backend_port if backend else self.port
        role = 'opencode' if backend else 'openchamber'
        try:
            verified = self.validate_listener(port, role)
        except Exception:
            raise _Failure('listener_unverified') from None
        if verified is not True:
            raise _Failure('listener_unverified')
        base = f'http://127.0.0.1:{port}'
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity', 'Origin': base}
        if backend:
            headers['Authorization'] = self.authorization
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        opener = self.public if backend or not authenticated else self.ui
        request = urllib.request.Request(base + path, data=data, headers=headers)
        try:
            try:
                response = opener.open(request, timeout=self.remaining())
            except urllib.error.HTTPError as error:
                response = error
            with response:
                if response.status != expected_status:
                    raise _Failure('http_error')
                content_type = response.headers.get_content_type()
                if content_type != 'application/json' and not content_type.endswith('+json'):
                    raise _Failure('invalid_response')
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise _Failure('invalid_response')
                declared = response.headers.get('Content-Length')
                if declared is not None and (not declared.isdecimal() or int(declared) > MAX_RESPONSE):
                    raise _Failure('response_too_large')
                chunks, length = [], 0
                while True:
                    self.remaining()
                    block = response.read1(min(65536, MAX_RESPONSE + 1 - length))
                    if not block:
                        break
                    length += len(block)
                    if length > MAX_RESPONSE:
                        raise _Failure('response_too_large')
                    chunks.append(block)
                self.remaining()
                return _json(b''.join(chunks))
        except (TimeoutError, urllib.error.URLError, OSError):
            raise _Failure('http_unavailable') from None

    def oc(self, path):
        return self.request(path)

    def backend(self, path, directory=None):
        if directory is not None:
            path += ('&' if '?' in path else '?') + urllib.parse.urlencode({'location[directory]': directory})
        return self.request(path, backend=True)


def _health(http, expected_openchamber, expected_opencode, expected_binary, ui_password):
    health = _object(http.request('/health', authenticated=False))
    if (health.get('status') != 'ok' or health.get('openchamberVersion') != expected_openchamber
            or any(health.get(key) is not True for key in ('openCodeRunning', 'isOpenCodeReady', 'openCodeSecureConnection'))
            or health.get('openCodeAuthSource') != 'user-env'
            or health.get('opencodeBinaryResolved') != expected_binary
            or health.get('opencodeBinarySource') not in ('env', 'policy')):
        raise _Failure('health_mismatch')
    port = health.get('openCodePort')
    if type(port) is not int or not 1024 <= port <= 65535 or port == http.port:
        raise _Failure('health_mismatch')
    http.backend_port = port
    info = _object(http.backend('/api/info'))
    if info.get('version') != expected_opencode or type(info.get('pid')) is not int or info['pid'] <= 0:
        raise _Failure('health_mismatch')
    before = _object(http.request('/auth/session', authenticated=False, expected_status=401))
    if before.get('authenticated') is not False:
        raise _Failure('health_mismatch')
    login = _object(http.request('/auth/session', body={'password': ui_password}))
    if login.get('authenticated') is not True:
        raise _Failure('health_mismatch')
    if _object(http.oc('/auth/session')).get('authenticated') is not True:
        raise _Failure('health_mismatch')


def _sessions(http, directories):
    cursor, seen_cursors, seen_sessions = None, set(), set()
    for _ in range(MAX_SESSION_PAGES):
        query = {'limit': '100'}
        if cursor is not None:
            query['cursor'] = cursor
        page = _object(http.backend('/api/session?' + urllib.parse.urlencode(query)))
        records = _array(_data(page))
        for session in records:
            session = _object(session)
            identifier = _text(session.get('id'))
            if identifier in seen_sessions:
                raise _Failure('invalid_response')
            seen_sessions.add(identifier)
            if len(seen_sessions) > MAX_ITEMS:
                raise _Failure('inspection_limit')
            directories.add(_directory(_object(session.get('location')).get('directory')))
            metadata = _object(session.get('metadata', {}))
            namespace = _object(metadata.get('openchamber', {}))
            goal = namespace.get('goal')
            if goal is not None:
                status = _object(goal).get('status')
                if status == 'active':
                    return 'session_goal'
                if status not in ('paused', 'blocked', 'budgetLimited', 'complete'):
                    raise _Failure('invalid_response')
            if namespace.get('lead') is not None:
                _object(namespace['lead'])
                return 'session_lead'
        cursor = _object(page.get('cursor')).get('next')
        if cursor is None:
            return None
        cursor = _text(cursor)
        if cursor in seen_cursors:
            raise _Failure('invalid_response')
        seen_cursors.add(cursor)
    raise _Failure('inspection_limit')


def _activity(http):
    terminals = _rows(http.oc('/api/terminal/sessions'), 'sessions', {'running', 'exited'})
    if any(item['status'] == 'running' for item in terminals):
        return 'openchamber_terminals'
    active = _object(_data(http.backend('/api/session/active')))
    for value in active.values():
        if _object(value).get('type') != 'running':
            raise _Failure('invalid_response')
    if active:
        return 'opencode_sessions'
    jobs = _rows(http.backend('/api/experimental/job?status=running'), 'data', {'running', 'completed', 'error', 'cancelled'})
    if any(item['status'] == 'running' for item in jobs):
        return 'opencode_jobs'
    status = _object(http.oc('/api/openchamber/scheduled-tasks/status'))
    for flag, count in (('hasEnabledScheduledTasks', 'enabledScheduledTasksCount'),
                        ('hasRunningScheduledTasks', 'runningScheduledTasksCount')):
        value = status.get(count)
        if type(value) is not int or value < 0 or _boolean(status.get(flag)) != (value > 0):
            raise _Failure('invalid_response')
    if status['hasEnabledScheduledTasks'] or status['hasRunningScheduledTasks']:
        return 'scheduled_tasks'
    warming = _object(http.oc('/api/session-warming'))
    for item in _rows(warming, 'sessions'):
        _text(item.get('sessionId'))
        until = item.get('warmUntil')
        if until is not None and (type(until) not in (int, float) or not math.isfinite(until)):
            raise _Failure('invalid_response')
    if _boolean(warming.get('enabled')):
        return 'session_warming'
    settings = _object(http.oc('/api/config/settings'))
    memory = _boolean(settings.get('agentMemoryToolEnabled', False))
    dreaming = _boolean(settings.get('agentMemoryDreamingEnabled', False))
    if memory and dreaming:
        return 'memory_dreaming'
    queues = _rows(http.oc('/api/message-queue'), 'sessions')
    for item in queues:
        if 'sendingId' not in item:
            raise _Failure('invalid_response')
        sending = item['sendingId']
        if sending is not None:
            _text(sending)
        if _array(item.get('items')) or sending is not None:
            return 'message_queue'
    reviews = _rows(http.oc('/api/auto-review'), 'runs', {'running', 'clean', 'disputed', 'limit', 'failed', 'stopped'})
    if any(item['status'] == 'running' for item in reviews):
        return 'auto_review'
    if _rows(http.oc('/api/pr-watch'), 'watches'):
        return 'pr_watch'
    if _rows(http.oc('/api/extension-waits'), 'waits'):
        return 'extension_waits'
    automations = _rows(http.backend('/api/experimental/automation'), 'data', {'active', 'paused', 'done'})
    if any(item['status'] == 'active' for item in automations):
        return 'opencode_automations'
    loaded = _array(http.backend('/api/debug/location'))
    directories = {_directory(_object(item).get('directory')) for item in loaded}
    for project in _array(settings.get('projects', [])):
        directories.add(_directory(_object(project).get('path')))
    reason = _sessions(http, directories)
    if reason:
        return reason
    if len(directories) > MAX_LOCATIONS:
        raise _Failure('inspection_limit')
    loaded_directories = {_directory(item['directory']) for item in loaded}
    for directory in sorted(directories):
        # Inspect process-local state only in already loaded locations. Requests
        # for old project paths would unnecessarily boot a location's plugins.
        if directory in loaded_directories:
            for route, label in (('/api/shell', 'opencode_shells'), ('/api/pty', 'opencode_ptys')):
                value = _object(http.backend(route, directory))
                if _directory(_object(value.get('location')).get('directory')) != directory:
                    raise _Failure('invalid_response')
                rows = _rows(value, 'data', {'running', 'exited', 'timeout', 'killed'} if route.endswith('shell') else {'running', 'exited'})
                if any(item['status'] == 'running' for item in rows):
                    return label
            for route in ('/api/permission/request', '/api/form'):
                value = _object(http.backend(route, directory))
                if _directory(_object(value.get('location')).get('directory')) != directory:
                    raise _Failure('invalid_response')
                if _rows(value, 'data'):
                    return 'opencode_pending_requests'
            configs = _array(http.backend('/api/config', directory))
            warming = False
            for config in configs:
                config = _object(config)
                if config.get('type') == 'document':
                    info = _object(config.get('info'))
                    if 'warming' in info:
                        warming = info['warming']
                        if type(warming) is not bool and not isinstance(warming, dict):
                            raise _Failure('invalid_response')
                elif config.get('type') != 'directory':
                    raise _Failure('invalid_response')
            if warming is True or isinstance(warming, dict):
                return 'opencode_warming'
        workflows = _rows(http.oc('/api/openchamber/workflows?' + urllib.parse.urlencode({'directory': directory})), 'runs')
        for run in workflows:
            if run.get('state') in ('running', 'awaiting-approval'):
                return 'workflows'
            if run.get('state') not in ('completed', 'failed', 'stopped', 'declined'):
                raise _Failure('invalid_response')
    return None


def probe(*, port, expected_openchamber, expected_opencode, expected_binary,
          ui_password, backend_password, validate_listener, health_only=False,
          timeout=3.0, budget=30.0):
    """Return only ``{'state': ..., 'reason': fixed_code}``; never expose payloads.

    ``validate_listener(port, role)`` must independently prove the listener is a
    loopback-only socket owned by the expected running service and return exactly
    True. It is called before every request (roles: openchamber/opencode). The
    caller must not replace this with trust in a PID from an HTTP response.
    Health-only mode returns healthy/unknown and never requires idle activity.
    """
    try:
        if (type(port) is not int or not 1024 <= port <= 65535 or type(health_only) is not bool
                or not callable(validate_listener) or type(timeout) not in (int, float)
                or type(budget) not in (int, float) or not math.isfinite(timeout)
                or not math.isfinite(budget) or not 0 < timeout <= 10 or not 0 < budget <= 60):
            raise _Failure('invalid_arguments')
        _directory(expected_binary)
        _text(expected_openchamber); _text(expected_opencode)
        if any(not isinstance(value, str) or not 24 <= len(value) <= 16384
               or any(ord(char) < 32 or ord(char) == 127 for char in value)
               for value in (ui_password, backend_password)):
            raise _Failure('credentials_invalid')
        if not health_only and (expected_openchamber, expected_opencode) not in ACTIVITY_VERSIONS:
            raise _Failure('unsupported_version')
        http = _HTTP(port, backend_password, validate_listener, timeout, budget)
        _health(http, expected_openchamber, expected_opencode, expected_binary, ui_password)
        if health_only:
            return {'state': 'healthy', 'reason': 'healthy'}
        reason = _activity(http)
        return {'state': 'busy', 'reason': reason} if reason else {'state': 'idle', 'reason': 'idle'}
    except _Failure as error:
        return {'state': 'unknown', 'reason': str(error)}
    except Exception:
        # Callback/HTTP/JSON failures may include secrets or remote response
        # fragments in their exception message. They never leave this boundary.
        return {'state': 'unknown', 'reason': 'probe_error'}
