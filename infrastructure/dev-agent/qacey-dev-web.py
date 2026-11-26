#!/usr/bin/python3
"""Explicit root gateway operations; never activates native services or prints credentials."""
import argparse
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_config as web

HOST_ROOT = Path('/')
ROOT_UID = 0


def run(command):
    result = subprocess.run(command, env=web.SYSTEM_ENV, capture_output=True, text=True)
    if result.returncode:
        # Compose errors can repeat a secret. Keep command output out of logs/chat.
        raise RuntimeError('Gateway command failed; inspect the service from the operator terminal without sharing secret output.')
    return result.stdout


def check(*, require_socket=False, verified_oracle_route=None):
    identity = web.development_record(HOST_ROOT)
    directory = HOST_ROOT / 'etc/qacey-dev/web'
    path = directory / 'installation.json'
    web.trusted_parents(path, HOST_ROOT); web.trusted(path)
    record = web.parse_json(path.read_text())
    if (not isinstance(record, dict) or record.get('schema') != 1 or record.get('ready') is not True
            or any(record.get(k) != identity[k] for k in ('user', 'uid', 'gid', 'home'))):
        raise ValueError('Gateway provisioning is incomplete or the development account changed.')
    web.validate_settings(record['settings'])
    web.verify_files(directory, record)
    if require_socket and verified_oracle_route != record['files'][web.ORACLE_ROUTE]:
        raise ValueError('Verify the installed Oracle route and edge access-log markers, then supply '
                         '--verified-oracle-route with the verified fragment SHA-256.')
    web.secret_values(directory / 'oauth2.env', 'oauth')
    web.secret_values(directory.parent / 'openchamber.env', 'native')
    command, _ = web.compose_command(directory)
    web.check_compose_version(run([*web.DOCKER, 'compose', 'version', '--short']).strip())
    run([*command, 'config', '--quiet'])
    if require_socket:
        socket = HOST_ROOT / 'run/qacey-dev-proxy/backend.sock'
        web.trusted_parents(socket, HOST_ROOT)
        info = socket.lstat()
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != identity['uid'] or info.st_gid != identity['gid']
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Start the private native proxy socket and verify its account and mode 0600 first.')
        # is-active with several units succeeds when any unit is active. Require each.
        for unit in ('qacey-openchamber.service', 'qacey-dev-proxy.socket', 'qacey-codex-tmux.service'):
            run(['/usr/bin/systemctl', 'is-active', '--quiet', unit])
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('check', 'start', 'stop', 'status'))
    parser.add_argument('--verified-oracle-route', metavar='SHA256',
                        help='For start: digest of the Oracle fragment verified on the edge using the runbook.')
    args = parser.parse_args(argv)
    if args.verified_oracle_route is not None and args.action != 'start':
        parser.error('--verified-oracle-route is used only with start.')
    if os.geteuid() != ROOT_UID: raise PermissionError('Gateway lifecycle commands require the operator root terminal.')
    web.ROOT_UID = ROOT_UID
    # Only root can open the provisioner's permanent private lock object.
    with web.gateway_lock(HOST_ROOT):
        if args.action in ('check', 'start'):
            command = check(require_socket=args.action == 'start', verified_oracle_route=args.verified_oracle_route)
            if args.action == 'start': run([*command, 'up', '-d', '--force-recreate'])
            print('Gateway started; verify TLS, identity and mobile acceptance.' if args.action == 'start'
                  else 'Gateway configuration and private secret-file checks passed. No service was started.')
        elif args.action == 'stop':
            # Revocation must still work if credentials/configuration are missing or broken.
            ids = run([*web.DOCKER, 'container', 'ls', '--all', '--filter', 'label=com.docker.compose.project=qacey-dev-web',
                       '--format', '{{.ID}}']).splitlines()
            if any(not re.fullmatch(r'[a-f0-9]{12,64}', value) for value in ids):
                raise ValueError('Docker returned an unexpected container identifier.')
            if ids: run([*web.DOCKER, 'container', 'stop', '--time', '10', *ids])
            print('Gateway containers stopped. Native Codex tmux sessions were left running.')
        else:
            print(run([*web.DOCKER, 'container', 'ls', '--all', '--filter', 'label=com.docker.compose.project=qacey-dev-web',
                       '--format', 'table {{.Names}}\t{{.Status}}']).strip())
    return 0


if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc: sys.exit(f'Gateway operation: {exc}')
