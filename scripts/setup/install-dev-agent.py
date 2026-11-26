#!/usr/bin/python3
"""Install opt-in native development helpers and disabled units. Defaults to dry-run."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'infrastructure/dev-agent'
HOST_ROOT = Path('/')
ROOT_UID = 0
spec = importlib.util.spec_from_file_location('qacey_codex_provision_dependency', Path(__file__).with_name('install-codex.py'))
foundation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(foundation)

LIB_FILES = ('dev_context.py', 'qacey-dev.py', 'install_runtime.py', 'release.json',
             'sync_config.py', 'mcp_config.py', 'shared/AGENTS.md', 'shared/mcp.json',
             'runtime/openchamber/package.json', 'runtime/openchamber/package-lock.json')
UNITS = ('qacey-openchamber.service', 'qacey-codex-tmux.service',
         'qacey-dev-proxy.socket', 'qacey-dev-proxy.service')
FOUNDATION_REFRESH = ('codex_account.py', 'seed_home.py')


def source_version():
    result = subprocess.run(['/usr/bin/git', '-c', 'safe.directory=' + str(ROOT),
                             '-C', str(ROOT), 'rev-parse', '--verify', 'HEAD'],
                            env=foundation.SYSTEM_ENV, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def trusted_parents(path):
    for parent in reversed(path.parents):
        if parent.is_relative_to(HOST_ROOT):
            foundation.trusted(parent, directory=True, optional=True)


class Provision:
    def __init__(self, port=None, node=None):
        self.port, self.node = port, node
        self.lib = HOST_ROOT / 'usr/local/lib/qacey-dev'
        self.directory = HOST_ROOT / 'etc/qacey-dev'
        self.record = self.directory / 'installation.json'
        self.launcher = HOST_ROOT / 'usr/local/bin/qacey-dev'
        self.unit_dir = HOST_ROOT / 'etc/systemd/system'
        self.policy = HOST_ROOT / 'etc/openchamber/policy.json'
        foundation.HOST_ROOT, foundation.ROOT_UID = HOST_ROOT, ROOT_UID

    def preflight(self):
        origin = HOST_ROOT / 'etc/qacey-codex/installation.json'
        trusted_parents(origin)
        foundation.trusted(origin, directory=False)
        basis = json.loads(origin.read_text())
        if basis.get('schema') != 1 or basis.get('ready') is not True:
            raise ValueError('Complete the native Codex foundation first.')
        home = foundation.checked_home(basis['user'], basis['home'])
        checked, account = foundation.Provision(basis['user'], home).preflight()
        if account is None or (checked['uid'], checked['gid']) != (account.pw_uid, account.pw_gid):
            raise ValueError('The foundation account no longer matches its record.')
        for name in FOUNDATION_REFRESH:
            foundation.trusted(HOST_ROOT / 'usr/local/lib/qacey-codex' / name, directory=False)
        for path in (self.record, self.launcher, self.lib, self.policy, self.unit_dir / UNITS[0]):
            trusted_parents(path)
        exists = foundation.trusted(self.record, directory=False, optional=True)
        previous = json.loads(self.record.read_text()) if exists else None
        if previous is not None and (not isinstance(previous, dict) or previous.get('schema') != 1
                                     or any(previous.get(key) != basis[key] for key in ('user', 'home', 'uid', 'gid'))):
            raise ValueError('Development installation belongs to a different account.')
        settings = previous or {}
        port = self.port if self.port is not None else settings.get('port', 3939)
        node = self.node if self.node is not None else settings.get('node', '/usr/bin/node')
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Choose a nonprivileged web port from 1024 to 65535.')
        if not isinstance(node, str):
            raise ValueError('Use a canonical absolute Node executable path.')
        path = Path(node)
        if (not path.is_absolute() or not path.name or str(path) != node or '..' in path.parts
                or any(not char.isprintable() for char in node)):
            raise ValueError('Use a canonical absolute Node executable path.')
        for path in (self.directory, self.lib):
            if foundation.trusted(path, directory=True, optional=True) and previous is None:
                raise ValueError(f'Refusing unrelated installation directory: {path}')
        environment = foundation.trusted(self.directory / 'openchamber.env', directory=False, optional=True)
        if environment is not None and stat.S_IMODE(environment.st_mode) != 0o600:
            raise ValueError('Existing OpenChamber service environment must be root-owned mode 0600.')
        destinations = [self.launcher, *(self.lib / name for name in LIB_FILES), *(self.unit_dir / name for name in UNITS)]
        for path in destinations:
            trusted_parents(path)
            if foundation.trusted(path, directory=False, optional=True) and previous is None:
                raise ValueError(f'Refusing to overwrite unrelated file: {path}')
        for name in UNITS:
            if previous is None:
                foundation.check_unit_collisions(name)
            else:
                for directory in foundation.SYSTEM_UNIT_DIRS:
                    root = HOST_ROOT / directory
                    if (root / (name + '.d')).exists() or (root / (name + '.d')).is_symlink():
                        raise ValueError(f'Unexpected service drop-in: {root / (name + ".d")}')
                    candidate = root / name
                    if root != self.unit_dir and (candidate.exists() or candidate.is_symlink()):
                        raise ValueError(f'Shadowed service unit: {candidate}')
        policy_info = foundation.trusted(self.policy, directory=False, optional=True)
        policy = json.loads(self.policy.read_text()) if policy_info else {}
        if not isinstance(policy, dict) or policy.get('enterpriseMode') is True:
            raise ValueError('Existing OpenChamber policy requires explicit review.')
        if policy_info and not policy_info.st_mode & 0o004:
            raise ValueError('Existing OpenChamber policy is private; review it before sharing with this account.')
        if self.policy.parent.exists() and not self.policy.parent.stat().st_mode & 0o001:
            raise ValueError('OpenChamber policy directory is not readable by the development account.')
        release = json.loads((ASSETS / 'release.json').read_text())
        expected = str(home / '.local/share/qacey-dev/runtime' / ('opencode-' + release['opencode']['version']) / 'opencode')
        current_binary = policy.get('opencodeBinary')
        before = current_binary
        allowed = [None, expected]
        if previous:
            managed = str(home / '.local/share/qacey-dev/runtime' / ('opencode-' + previous['opencode_version']) / 'opencode')
            allowed.append(managed)
            if previous.get('ready') is False and 'policy_before' in previous:
                if expected != managed:
                    raise ValueError('Finish the interrupted OpenCode upgrade before selecting a different release.')
                before = previous['policy_before']
                allowed = [before, managed]
        if current_binary not in allowed:
            raise ValueError('OpenChamber already selects a different OpenCode binary.')
        policy['opencodeBinary'] = expected
        record = dict(schema=1, ready=False, user=basis['user'], uid=basis['uid'], gid=basis['gid'],
                      home=basis['home'], port=port, node=node, policy_before=before,
                      opencode_version=release['opencode']['version'], openchamber_version=release['openchamber']['version'])
        return record, policy

    def apply(self):
        with foundation.provision_lock():
            record, policy = self.preflight()
            record['source_version'] = source_version()
            self.directory.mkdir(mode=0o755, exist_ok=True)
            self.directory.chmod(0o755)
            foundation.write_record(self.record, record)
            self.lib.mkdir(mode=0o755, exist_ok=True)
            self.lib.chmod(0o755)
            for name in LIB_FILES:
                destination = self.lib / name
                destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                for parent in destination.parents:
                    if parent.is_relative_to(self.lib): parent.chmod(0o755)
                foundation.write_atomic(destination, (ASSETS / name).read_bytes(), 0o644)
            foundation.write_atomic(self.launcher, (ASSETS / 'qacey-dev').read_bytes(), 0o755)
            for name in UNITS:
                unit = (ASSETS / (name + '.in')).read_text().replace('@USER@', record['user'])
                unit = unit.replace('@HOME@', quoted(record['home'])).replace('@PORT@', str(record['port']))
                foundation.write_atomic(self.unit_dir / name, unit.encode(), 0o644)
            if not self.policy.parent.exists():
                # Publish the directory with its traversal mode in the mkdir syscall.
                previous_umask = os.umask(0o022)
                try:
                    self.policy.parent.mkdir(mode=0o755)
                finally:
                    os.umask(previous_umask)
            foundation.write_atomic(self.policy, (json.dumps(policy, indent=2) + '\n').encode(), 0o644)
            for name in FOUNDATION_REFRESH:
                foundation.write_atomic(HOST_ROOT / 'usr/local/lib/qacey-codex' / name,
                                        (ROOT / 'infrastructure/codex' / name).read_bytes(), 0o644)
            del record['policy_before']
            record['ready'] = True
            foundation.write_record(self.record, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--port', type=int)
    parser.add_argument('--node')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and os.geteuid() != ROOT_UID:
        raise PermissionError('Root is required to apply development provisioning.')
    provision = Provision(args.port, args.node)
    record, _ = provision.preflight()
    print(f"Account: {record['user']}\nHome: {record['home']}\nOpenChamber: 127.0.0.1:{record['port']}\nNode: {record['node']}")
    if args.apply:
        provision.apply()
        print('Helpers and disabled units installed. No runtime, credentials or services were started.')
    else:
        print('Dry run. Pass --apply as root to install helpers and disabled units.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f'Development provisioning: {exc}')
