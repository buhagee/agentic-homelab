#!/usr/bin/python3 -I
"""Use the provisioned native development account and explicit shared baseline."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_context
import sync_config

ASSETS = Path(__file__).resolve().parent
TMUX_SOCKET = '/run/qacey-codex-tmux/server.sock'
UNITS = ('qacey-openchamber.service', 'qacey-codex-tmux.service',
         'qacey-dev-proxy.socket', 'qacey-dev-proxy.service')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    operations = parser.add_subparsers(dest='operation', required=True,
                                      metavar='{sync,install-runtime,openchamber,codex,status}')
    sync = operations.add_parser('sync', allow_abbrev=False)
    sync.add_argument('--source', type=Path, default=ASSETS / 'shared')
    sync.add_argument('--apply', action='store_true')
    operations.add_parser('install-runtime', allow_abbrev=False).add_argument('--apply', action='store_true')
    operations.add_parser('openchamber')
    operations.add_parser('status')
    operations.add_parser('codex', help='Attach to a persistent project session.').add_argument('project')
    operations.add_parser('_codex-run').add_argument('project')
    args = parser.parse_args(argv)
    account, record = dev_context.current()
    if args.operation == 'sync':
        # Preflight the shared skill path before applying any configuration.
        skills = account.home / '.agents/skills'
        dev_context.private_path(account.home, skills, directory=True, optional=True)
        actions = sync_config.sync(account.home, args.source, args.apply)
        if args.apply:
            dev_context.private_path(account.home, skills, directory=True, create=True)
        print('\n'.join(actions) if actions else 'Shared configuration is unchanged.')
        return 0
    if args.operation == 'install-runtime':
        runtime = dev_context.load_module('qacey_dev_install_runtime', ASSETS / 'install_runtime.py')
        return runtime.install(account, record, args.apply)
    if args.operation == 'status':
        return subprocess.run(['/usr/bin/systemctl', 'show', '--no-pager',
                               '--property=Id,ActiveState,SubState,UnitFileState', *UNITS],
                              env=account.environment(), cwd=account.home).returncode
    if args.operation in ('codex', '_codex-run'):
        project = dev_context.foundation.checked_project(account, args.project, account.environment())
        if args.operation == '_codex-run':
            env = dev_context.environment(account, persistent=True)
            os.chdir(project)
            return os.execve(account.codex, [str(account.codex), '-C', str(project)], env)
        session = 'codex-' + hashlib.sha256(str(project).encode()).hexdigest()[:20]
        # Multiple shell-command arguments are executed directly by tmux, without
        # shell interpolation. -N prevents a server escaping service ownership.
        return subprocess.run(['/usr/bin/tmux', '-N', '-S', TMUX_SOCKET, 'new-session',
                               '-A', '-s', session, '-c', str(project),
                               '/usr/local/bin/qacey-dev', '_codex-run', str(project)],
                              env=dev_context.environment(account, tmux_client=True), cwd=project).returncode
    dev_context.check_openchamber_settings(account)
    env = dev_context.environment(account)
    for name in ('OPENCHAMBER_UI_PASSWORD', 'OPENCODE_PASSWORD'):
        value = os.environ.get(name, '')
        if len(value) < 24 or any(ord(char) < 32 for char in value):
            raise ValueError(f'{name} must be set to a strong secret in the private service environment file.')
        env[name] = value
    runtime = dev_context.runtime_selection(account, record)
    dev_context.private_path(account.home, account.home / '.config/openchamber', directory=True, create=True)
    env.update(OPENCHAMBER_DATA_DIR=str(account.home / '.config/openchamber'),
               OPENCHAMBER_OPENCODE_HOSTNAME='127.0.0.1',
               OPENCHAMBER_OPENCODE_CWD=str(account.home / 'projects'),
               OPENCODE_BINARY=str(runtime['opencode']), OPENCHAMBER_RELAY_HOST='on',
               OPENCODE_DISABLE_AUTOUPDATE='1',
               OPENCHAMBER_UI_SESSION_TTL_HOURS='2',
               PATH=f"{runtime['node'].parent}:{env['PATH']}")
    command = [str(runtime['node']), str(runtime['openchamber'] / 'build/bin/cli.js'),
               'serve', '--foreground', '--host', '127.0.0.1', '--port', str(record['port'])]
    os.chdir(account.home / 'projects')
    return os.execve(runtime['node'], command, env)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f'qacey-dev: {exc}')
