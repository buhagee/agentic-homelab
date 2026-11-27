#!/usr/bin/env python3
"""Disposable native packaging, MCP, skills and PTY acceptance; no model calls or login."""
import argparse
import asyncio
import base64
import json
import http.cookiejar
import os
from pathlib import Path
import secrets
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'infrastructure/dev-agent'
sys.path.insert(0, str(ASSETS))
import install_runtime
import sync_config
import deployment_probe


def command(argv, env, cwd):
    return subprocess.run([str(value) for value in argv], env=env, cwd=cwd,
                          capture_output=True, text=True, check=True, timeout=60).stdout


def fixture(home, env):
    project = home / 'projects/fixture'; project.mkdir(parents=True)
    command(['/usr/bin/git', 'init', '-q', project], env, home)
    source = home / 'source'; source.mkdir()
    (source / 'AGENTS.md').write_text('Disposable runtime fixture; do not perform any work.\n')
    (source / 'mcp.json').write_text(json.dumps({'schema': 1, 'servers': {
        'fixture_local': {'transport': 'stdio', 'command': '/usr/bin/false', 'args': ['space separated'],
                          'cwd': '{home}', 'env_vars': ['QACEY_TEST_STDIO'], 'enabled': False},
        'fixture_remote': {'transport': 'http', 'url': 'https://example.invalid/mcp',
                           'bearer_token_env_var': 'QACEY_TEST_BEARER',
                           'env_http_headers': {'X-Fixture': 'QACEY_TEST_HEADER'}, 'enabled': False}}}))
    sync_config.sync(home, source, apply=True)
    assert sync_config.sync(home, source) == []
    fixtures = {'qacey-shared-global': home / '.agents/skills', 'qacey-shared-project': project / '.agents/skills',
                'qacey-native-global': home / '.config/opencode/skills', 'qacey-native-project': project / '.opencode/skills'}
    for name, parent in fixtures.items():
        directory = parent / name; directory.mkdir(parents=True)
        (directory / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Disposable discovery fixture.\n---\nTest fixture only.\n')
    return project, {key: str(value / key / 'SKILL.md') for key, value in fixtures.items()}


def opencode_skills(binary, project, env, fixtures):
    password = secrets.token_urlsafe(32)
    environment = dict(env, OPENCODE_PASSWORD=password)
    process = subprocess.Popen([str(binary), 'serve', '--stdio', '--port', '0', '--hostname', '127.0.0.1'],
                               cwd=project, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            if not ready.select(20): raise RuntimeError('OpenCode readiness timed out.')
            url = json.loads(process.stdout.readline())['url']
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1': raise ValueError('Unexpected OpenCode listener.')
        auth = 'Basic ' + base64.b64encode(('opencode:' + password).encode()).decode()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        query = urllib.parse.urlencode({'location[directory]': str(project)})
        def get(path):
            request = urllib.request.Request(url + path + '?' + query, headers={'Authorization': auth})
            with opener.open(request, timeout=3) as response: return json.load(response)
        # Plugin/skill discovery is asynchronous; a one-shot listing can be empty.
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            plugins = get('/api/plugin').get('data', [])
            if plugins: break
            time.sleep(.05)
        else: raise RuntimeError('OpenCode plugin startup timed out.')
        assert not [plugin for plugin in plugins if plugin.get('state', {}).get('status') == 'failed']
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            skills = {item['id']: item['path'] for item in get('/api/skill').get('data', [])}
            if all(skills.get(name) == path for name, path in fixtures.items()): break
            time.sleep(.05)
        else: raise RuntimeError('OpenCode did not discover the shared/native skill fixtures.')
    finally:
        process.stdin.close()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        process.stdout.close()
    assert process.returncode == 0
    print('OpenCode ready-state MCP parsing and default global/project skill discovery: PASS')


async def codex_skills(binary, project, env, fixtures):
    process = await asyncio.create_subprocess_exec(str(binary), 'app-server', '--listen', 'stdio://', '--strict-config',
                                                   cwd=project, env=env, stdin=asyncio.subprocess.PIPE,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stderr = asyncio.create_task(process.stderr.read())
    async def send(value):
        process.stdin.write((json.dumps(value) + '\n').encode()); await process.stdin.drain()
    async def receive(identifier):
        async def read():
            while True:
                line = await process.stdout.readline()
                if not line: raise RuntimeError('Codex app-server exited before its response.')
                result = json.loads(line)
                if result.get('id') == identifier and ('result' in result or 'error' in result): return result
                if 'id' in result and 'method' in result: raise RuntimeError('Unexpected Codex request; no action taken.')
        return await asyncio.wait_for(read(), timeout=20)
    try:
        await send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'qacey_fixture', 'version': '1.0.0'},
                          'capabilities': {'experimentalApi': False, 'explicitGatewayOauth': True}}})
        assert 'result' in await receive(1)
        await send({'method': 'initialized'})
        await send({'id': 2, 'method': 'skills/list', 'params': {'cwds': [str(project)], 'forceReload': True}})
        result = (await receive(2))['result']['data'][0]
        assert not result['errors']
        skills = {item['name']: item['path'] for item in result['skills'] if item['enabled']}
        assert all(skills.get(name) == path for name, path in fixtures.items() if name.startswith('qacey-shared-'))
    finally:
        process.stdin.close()
        try: await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.terminate()
            try: await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError: process.kill(); await process.wait()
        await stderr
    assert process.returncode == 0
    print('Codex strict config/MCP and default global/project skill discovery: PASS')


def openchamber_backend(node, package, binary, project, env):
    # The released CLI rejects port 0. A private ephemeral fixture uses a high port;
    # collision is a startup failure, never a request to adopt an existing server.
    port = 49152 + secrets.randbelow(16384)
    url = f'http://127.0.0.1:{port}'
    password = secrets.token_urlsafe(36)
    environment = dict(env, OPENCODE_BINARY=str(binary), OPENCHAMBER_OPENCODE_HOSTNAME='127.0.0.1',
                       OPENCHAMBER_OPENCODE_CWD=str(project), OPENCHAMBER_DATA_DIR=str(Path(env['HOME']) / '.config/openchamber'),
                       OPENCHAMBER_RELAY_HOST='off', OPENCHAMBER_UI_PASSWORD=password,
                       OPENCODE_PASSWORD=secrets.token_urlsafe(36), SHELL='/bin/sh')
    preload = None
    if not Path('/etc/openchamber/policy.json').exists() or json.loads(Path('/etc/openchamber/policy.json').read_text()).get('opencodeBinary') != str(binary):
        preload = Path(env['HOME']) / 'no-policy-preload.cjs'
        preload.write_text(
            "const fs = require('node:fs');\n"
            "const orig = fs.readFileSync;\n"
            "fs.readFileSync = function(p, ...args) {\n"
            "  if (String(p) === '/etc/openchamber/policy.json') {\n"
            "    const err = new Error('ENOENT'); err.code = 'ENOENT'; throw err;\n"
            "  }\n"
            "  return orig.call(this, p, ...args);\n"
            "};\n"
        )
    argv = [str(node)]
    if preload is not None:
        argv.extend(['--require', str(preload)])
    argv.extend([str(package / 'build/bin/cli.js'), 'serve', '--foreground',
                 '--host', '127.0.0.1', '--port', str(port)])
    process = subprocess.Popen(argv, cwd=project, env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    unauth = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(opener, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url + path, data=data,
                                         headers={'Content-Type': 'application/json', 'Origin': url})
        try: response = opener.open(request, timeout=3)
        except urllib.error.HTTPError as error: response = error
        with response:
            payload = response.read(2 * 1024 * 1024)
            return response.status, (json.loads(payload) if 'json' in response.headers.get('Content-Type', '') else None)
    def fixture_listener(candidate, role):
        # Independently prove that both ports belong to this disposable process
        # tree before sending synthetic passwords. OpenChamber gives its backend
        # a separate process group; production ownership uses the systemd cgroup.
        if process.poll() is not None or role not in ('openchamber', 'opencode'):
            return False
        sockets = set()
        for table, loopback in (('/proc/net/tcp', '0100007F'),
                                ('/proc/net/tcp6', '00000000000000000000000001000000')):
            for line in Path(table).read_text().splitlines()[1:]:
                fields = line.split()
                address, raw_port = fields[1].split(':')
                if fields[3] != '0A' or int(raw_port, 16) != candidate:
                    continue
                if address != loopback or int(fields[7]) != os.geteuid():
                    return False
                sockets.add(fields[9])
        if not sockets:
            return False
        parents = {}
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                if entry.stat().st_uid != os.geteuid():
                    continue
                fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
                parents[int(entry.name)] = int(fields[1])
            except (FileNotFoundError, ProcessLookupError):
                continue
        descendants, pending = {process.pid}, [process.pid]
        while pending:
            parent = pending.pop()
            children = {pid for pid, owner in parents.items() if owner == parent} - descendants
            descendants.update(children); pending.extend(children)
        owned = set()
        for pid in descendants:
            try:
                entry = Path('/proc') / str(pid)
                for descriptor in (entry / 'fd').iterdir():
                    try:
                        link = os.readlink(descriptor)
                    except FileNotFoundError:
                        continue
                    if link.startswith('socket:[') and link.endswith(']'):
                        owned.add(link[8:-1])
            except (FileNotFoundError, ProcessLookupError):
                continue
        return sockets <= owned
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None: raise RuntimeError('OpenChamber exited before managed backend readiness.')
            try:
                status, health = request(unauth, '/health')
                if status == 200 and health.get('isOpenCodeReady') is True: break
            except urllib.error.URLError: pass
            time.sleep(.1)
        else: raise RuntimeError('OpenChamber managed OpenCode readiness timed out.')
        assert health['openCodeRunning'] is True and health['openCodeSecureConnection'] is True
        assert request(unauth, '/')[0] == 200
        assert request(unauth, '/auth/session')[0] == 401
        assert request(unauth, '/api/terminal/sessions')[0] == 401
        authenticated = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        assert request(authenticated, '/auth/session', {'password': password})[0] == 200
        assert request(authenticated, '/auth/session')[0] == 200
        pins = json.loads((ASSETS / 'release.json').read_text())
        probe_arguments = dict(port=port, expected_openchamber=pins['openchamber']['version'],
                               expected_opencode=pins['opencode']['version'], expected_binary=str(binary),
                               ui_password=password, backend_password=environment['OPENCODE_PASSWORD'],
                               validate_listener=fixture_listener)
        result = deployment_probe.probe(**probe_arguments, health_only=True)
        assert result == {'state': 'healthy', 'reason': 'healthy'}, result
        result = deployment_probe.probe(**probe_arguments)
        assert result == {'state': 'idle', 'reason': 'idle'}, result
        # An empty saved conversation exercises the real session metadata/page
        # envelope without sending a prompt or asking a provider to do work.
        backend_port = health['openCodePort']
        assert fixture_listener(backend_port, 'opencode')
        auth = 'Basic ' + base64.b64encode(('opencode:' + environment['OPENCODE_PASSWORD']).encode()).decode()
        create = urllib.request.Request(f'http://127.0.0.1:{backend_port}/api/session',
            data=json.dumps({'title': 'Disposable deployment probe'}).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': auth})
        with unauth.open(create, timeout=3) as response:
            assert response.status == 200 and isinstance(json.load(response)['data']['id'], str)
        result = deployment_probe.probe(**probe_arguments)
        assert result == {'state': 'idle', 'reason': 'idle'}, result
        print('Pinned authenticated native deployment health, empty-state and saved-session idle probes: PASS')
    finally:
        if process.poll() is None: process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
        try: os.killpg(process.pid, 0)
        except ProcessLookupError: pass
        else:
            os.killpg(process.pid, signal.SIGKILL)
            raise RuntimeError('OpenChamber left a child process after shutdown; fixture group was cleaned up.')
    print('OpenChamber owns a ready private authenticated OpenCode backend; application login boundary: PASS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opencode', type=Path); parser.add_argument('--openchamber', type=Path)
    parser.add_argument('--codex', type=Path); parser.add_argument('--node', type=Path, default=Path(shutil.which('node') or '/usr/bin/node'))
    args = parser.parse_args()
    provided = (args.opencode, args.openchamber, args.codex)
    if any(provided) and not all(provided): parser.error('Supply all three runtime paths or none (download and verify).')
    if os.geteuid() == 0: raise PermissionError('Run disposable native acceptance as a nonroot user.')
    release = json.loads((ASSETS / 'release.json').read_text())
    codex_release = json.loads((ROOT / 'infrastructure/codex/release.json').read_text())
    with tempfile.TemporaryDirectory(prefix='qacey-runtime-') as raw:
        home = Path(raw); bin_dir = home / '.local/bin'; bin_dir.mkdir(parents=True)
        temporary = home / 'tmp'; temporary.mkdir()
        env = dict(PATH=str(args.node.parent) + ':/usr/bin:/bin', HOME=str(home), CODEX_HOME=str(home / '.codex'),
                   XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'),
                   XDG_CACHE_HOME=str(home / '.cache'), XDG_STATE_HOME=str(home / '.local/state'),
                   TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary), LANG='C.UTF-8', TERM='dumb',
                   OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_AUTOUPDATE='1',
                   QACEY_TEST_STDIO='dummy', QACEY_TEST_BEARER='dummy', QACEY_TEST_HEADER='dummy')
        if not all(provided):
            account = SimpleNamespace(home=home, bin_dir=bin_dir, environment=lambda: dict(env))
            record = dict(node=str(args.node), opencode_version=release['opencode']['version'], openchamber_version=release['openchamber']['version'])
            install_runtime.install(account, record, apply=True)
            selected = json.loads((home / '.local/share/qacey-dev/runtime/installation.json').read_text())
            args.opencode, args.openchamber = Path(selected['opencode']), Path(selected['openchamber'])
            installer = home / 'codex-install.sh'
            install_runtime.download(codex_release['url'], installer, codex_release['sha256'])
            install_env = dict(env, CODEX_NON_INTERACTIVE='1', CODEX_INSTALL_DIR=str(bin_dir))
            for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR'):
                if name in os.environ: install_env[name] = os.environ[name]
            command(['/bin/sh', installer, '--release', codex_release['version']], install_env, home)
            args.codex = bin_dir / 'codex'
        assert command([args.opencode, '--version'], env, home).strip() == 'opencode v' + release['opencode']['version']
        assert command([args.codex, '--version'], env, home).strip() == 'codex-cli ' + codex_release['version']
        assert command([args.node, args.openchamber / 'build/bin/cli.js', '--version'], env, home).strip() == release['openchamber']['version']
        command([args.opencode, '--help'], env, home)
        command([args.node, args.openchamber / 'build/bin/cli.js', 'serve', '--help'], env, home)
        command([args.node, ROOT / 'scripts/testing/dev-pty-smoke.cjs', args.openchamber, home], env, home)
        project, fixtures = fixture(home, env)
        data = json.loads(command([args.codex, 'mcp', 'list', '--json'], env, project))
        assert {item['name'] for item in data} == {'fixture_local', 'fixture_remote'}
        assert all(item['enabled'] is False for item in data)
        command([args.codex, 'app-server', '--strict-config', '--print-startup-config'], env, project)
        config = command([args.opencode, '--standalone', 'debug', 'config'], env, project)
        assert 'fixture_local' in config and 'fixture_remote' in config
        opencode_skills(args.opencode, project, env, fixtures)
        asyncio.run(codex_skills(args.codex, project, env, fixtures))
        openchamber_backend(args.node, args.openchamber, args.opencode, project, env)
        print('Pinned native versions/help and native PTY spawn/input/resize/exit: PASS')


if __name__ == '__main__': main()
