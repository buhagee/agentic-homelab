#!/usr/bin/env python3
"""Isolated gateway syntax/HTTP/WebSocket checks. --docker additionally checks Compose.

No production files, provider login or live IdP are used. Local parser-only mode:
  python3 scripts/testing/check-dev-web.py --caddy /path/caddy --oauth2-proxy /path/oauth2-proxy
CI mode extracts the binaries from the pinned images and runs loopback fixtures:
  python3 scripts/testing/check-dev-web.py --docker
"""
import argparse
import base64
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'infrastructure/dev-agent'))
import web_config as web


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs)


def binary_from_image(image, path, destination):
    container = run(['docker', 'create', image]).stdout.strip()
    try: run(['docker', 'cp', container + ':' + path, str(destination)])
    finally: run(['docker', 'rm', container])
    destination.chmod(0o700)
    return destination


def fixture_environment(directory):
    environment = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
    for name, child in {'HOME': 'home', 'XDG_CONFIG_HOME': 'config', 'XDG_DATA_HOME': 'data',
                        'XDG_CACHE_HOME': 'cache', 'XDG_STATE_HOME': 'state', 'TMPDIR': 'tmp'}.items():
        path = directory / 'caddy-state' / child
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)
        environment[name] = str(path)
    environment['TMP'] = environment['TEMP'] = environment['TMPDIR']
    return environment


def check_adapted_transport(adapted, port, backend):
    servers = adapted['apps']['http']['servers']
    assert len(servers) == 1, 'Fixture must have exactly one HTTP server.'
    server = next(iter(servers.values()))
    assert server['listen'] == [f'127.0.0.1:{port}'], 'Fixture must bind only IPv4 loopback.'
    routes = server['routes']
    assert not any('host' in matcher for route in routes for matcher in route.get('match', [])), \
        'Fixture site must not add an implicit positive Host matcher.'
    # The production negative Host gate must remain reachable for the public Host.
    assert any(route.get('match') == [{'not': [{'host': ['dev.example.test']}]}]
               and any(handler.get('status_code') == 421 for handler in route.get('handle', []))
               for route in routes), 'Canonical Host rejection disappeared from the fixture.'
    assert any(handler.get('handler') == 'reverse_proxy'
               and handler.get('upstreams') == [{'dial': 'unix/' + str(backend)}]
               for route in routes for handler in route.get('handle', [])), 'Unix upstream differs.'


def transport_config(caddy, directory, config, port, backend, environment):
    actual = directory / 'transport.Caddyfile'
    actual.write_text(config.replace(':8080 {', f':{port} {{\n  bind 127.0.0.1')
                      .replace('unix//run/qacey-dev-proxy/backend.sock', 'unix/' + str(backend)))
    adapted = json.loads(run([str(caddy), 'adapt', '--config', str(actual), '--adapter', 'caddyfile'],
                             env=environment).stdout)
    check_adapted_transport(adapted, port, backend)
    return actual


class UnixHTTP(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            accept = base64.b64encode(hashlib.sha1((self.headers['Sec-WebSocket-Key'] +
                                      '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket'); self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept); self.end_headers()
            self.connection.settimeout(3)
            first = self.rfile.read(2)
            if len(first) == 2:
                size = first[1] & 127
                mask = self.rfile.read(4) if first[1] & 128 else bytes(4)
                data = self.rfile.read(size)
                data = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
                self.wfile.write(bytes([0x81, len(data)]) + data); self.wfile.flush()
            return
        data = json.dumps(dict(self.headers.items())).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers()
        self.wfile.write(data)

    do_POST = do_GET


def transport(caddy, directory, config, environment):
    backend = directory / 'backend.sock'
    server = UnixHTTP(str(backend), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = None
    try:
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        actual = transport_config(caddy, directory, config, port, backend, environment)
        with (directory / 'caddy.log').open('w') as log:
            process = subprocess.Popen([str(caddy), 'run', '--config', str(actual), '--adapter', 'caddyfile'],
                                       stdout=log, stderr=log, env=environment)
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1): break
                except OSError:
                    if process.poll() is not None: raise RuntimeError('Caddy exited during isolated transport startup.')
                    time.sleep(.03)
            else: raise RuntimeError('Caddy transport startup timed out.')

            def request(headers=None, method='GET'):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                try:
                    connection.request(method, '/', headers={'Host': 'dev.example.test', **(headers or {})})
                    response = connection.getresponse()
                    return response.status, response.read()
                finally: connection.close()

            status, body = request({'Authorization': 'Bearer disposable-fixture', 'Forwarded': 'host=evil.test;proto=http',
                                    'X-Forwarded-Proto': 'http'})
            assert status == 200
            headers = json.loads(body)
            assert headers['Host'] == 'dev.example.test' and headers['X-Forwarded-Proto'] == 'https'
            assert headers['X-Forwarded-Host'] == 'dev.example.test'
            assert headers['Authorization'] == 'Bearer disposable-fixture' and 'Forwarded' not in headers
            assert request({'Host': 'evil.test'})[0] == 421
            assert request({'Origin': 'https://evil.test'})[0] == 403
            assert request(method='POST')[0] == 403
            assert request({'Origin': 'https://dev.example.test'}, 'POST')[0] == 200
            handshake = {'Upgrade': 'websocket', 'Connection': 'Upgrade', 'Sec-WebSocket-Version': '13',
                         'Sec-WebSocket-Key': base64.b64encode(b'abcdefghijklmnop').decode()}
            assert request(handshake)[0] == 403
            assert request(dict(handshake, Upgrade='WebSocket'))[0] == 403
            assert request(dict(handshake, Origin='https://evil.test'))[0] == 403
            with socket.create_connection(('127.0.0.1', port), timeout=3) as connection:
                headers = {'Host': 'dev.example.test', **handshake, 'Origin': 'https://dev.example.test'}
                connection.sendall(('GET / HTTP/1.1\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in headers.items()) + '\r\n').encode())
                response = b''
                while b'\r\n\r\n' not in response:
                    part = connection.recv(1)
                    if not part or len(response) > 16384: raise RuntimeError('Incomplete/oversized WebSocket handshake.')
                    response += part
                assert response.startswith(b'HTTP/1.1 101')
                payload, mask = b'codex-terminal-fixture', b'abcd'
                connection.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload)))
                stream = connection.makefile('rb')
                assert stream.read(2) == bytes([0x81, len(payload)])
                assert stream.read(len(payload)) == payload
                stream.close()
        print('Unix HTTP/streaming WebSocket, bearer preservation, canonical forwarding and origin rejection: PASS')
    finally:
        if process:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        server.shutdown(); server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', action='store_true')
    parser.add_argument('--caddy', type=Path)
    parser.add_argument('--oauth2-proxy', type=Path)
    parser.add_argument('--transport', action='store_true')
    args = parser.parse_args()
    if not args.docker and not (args.caddy and args.oauth2_proxy): parser.error('Use --docker or both parser binary paths.')
    versions = web.read_versions(ROOT / 'versions.env')
    with tempfile.TemporaryDirectory(prefix='qacey-dev-web-') as raw:
        directory = Path(raw)
        caddy_environment = fixture_environment(directory)
        files = web.render(dict(hostname='dev.example.test', issuer='https://issuer.example.test',
                                client_id='disposable-client', emails=['owner@example.test'],
                                cert_resolver='letsencrypt', mfa_required=True),
                           dict(uid=1200, gid=1200), versions, ROOT / 'infrastructure/dev-agent/web')
        for name, data in files.items(): (directory / name).write_bytes(data)
        secret = 'OAUTH2_PROXY_CLIENT_SECRET=' + secrets.token_urlsafe(32) + '\nOAUTH2_PROXY_COOKIE_SECRET=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() + '\n'
        (directory / 'oauth2.env').write_text(secret); (directory / 'oauth2.env').chmod(0o600)
        if args.docker:
            web.check_compose_version(run(['docker', 'compose', 'version', '--short']).stdout.strip())
            run(['docker', 'compose', '--project-name', 'qacey-dev-web', '--project-directory', str(directory),
                 '--env-file', str(directory / 'versions.env'), '-f', str(directory / 'compose.yml'), 'config', '--quiet'])
            args.caddy = binary_from_image('caddy:' + versions['CADDY_VERSION'], '/usr/bin/caddy', directory / 'caddy')
            args.oauth2_proxy = binary_from_image('quay.io/oauth2-proxy/oauth2-proxy:' + versions['OAUTH2_PROXY_VERSION'],
                                                 '/bin/oauth2-proxy', directory / 'oauth2-proxy')
            print('Standalone Compose configuration and pinned container image availability: PASS')
        assert versions['CADDY_VERSION'].removesuffix('-alpine') in run([str(args.caddy), 'version'], env=caddy_environment).stdout
        assert versions['OAUTH2_PROXY_VERSION'] in run([str(args.oauth2_proxy), '--version']).stdout
        run([str(args.caddy), 'validate', '--config', str(directory / 'Caddyfile'), '--adapter', 'caddyfile'], env=caddy_environment)
        # Adapt without opening sockets, so parser-only runs catch Host/listen mistakes too.
        transport_config(args.caddy, directory, files['Caddyfile'].decode(), 48888,
                         directory / 'backend.sock', caddy_environment)
        oauth = directory / 'oauth2-proxy.cfg'
        oauth.write_text(oauth.read_text().replace('/etc/oauth2-proxy/allowed-emails.txt', str(directory / 'allowed-emails.txt')))
        environment = dict(PATH='/usr/bin:/bin', HOME=raw, **dict(line.split('=', 1) for line in secret.splitlines()))
        run([str(args.oauth2_proxy), '--config', str(oauth), '--config-test'], env=environment)
        print('Pinned Caddy and OAuth2 Proxy versions and actual configuration parsers: PASS')
        if args.transport or args.docker: transport(args.caddy, directory, files['Caddyfile'].decode(), caddy_environment)


if __name__ == '__main__': main()
