#!/usr/bin/python3
"""Prepare the opt-in authenticated gateway. Defaults to dry-run; never starts services."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'infrastructure/dev-agent'
sys.path.insert(0, str(ASSETS))
import web_config as web

HOST_ROOT = Path('/')
ROOT_UID = 0
LIB_FILES = ('web_config.py', 'qacey-dev-web.py')
# Docker can restore the adapter before the socket unit creates its parent.
PROXY_TMPFILES = b'd /run/qacey-dev-proxy 0755 root root -\n'


def write_atomic(path, data, mode=0o644):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data); stream.flush(); os.fchmod(stream.fileno(), mode)
            os.replace(temporary, path)
        finally: temporary.unlink(missing_ok=True)


def source_version():
    return subprocess.run(['/usr/bin/git', '-c', 'safe.directory=' + str(ROOT), '-C', str(ROOT),
                           'rev-parse', '--verify', 'HEAD'], env=web.SYSTEM_ENV,
                          capture_output=True, text=True, check=True).stdout.strip()


class Provision:
    def __init__(self, settings):
        self.settings = web.validate_settings(settings)
        self.directory = HOST_ROOT / 'etc/qacey-dev/web'
        self.record = self.directory / 'installation.json'
        self.lib = HOST_ROOT / 'usr/local/lib/qacey-dev-web'
        self.launcher = HOST_ROOT / 'usr/local/bin/qacey-dev-web'
        self.tmpfiles = HOST_ROOT / 'etc/tmpfiles.d/qacey-dev-proxy.conf'
        web.ROOT_UID = ROOT_UID

    def preflight(self):
        identity = web.development_record(HOST_ROOT)
        web.check_gateway_lock(HOST_ROOT, optional=True)
        for path in (self.directory, self.record, self.lib, self.launcher, self.tmpfiles):
            web.trusted_parents(path, HOST_ROOT, optional=True)
        if web.trusted(self.tmpfiles, optional=True) and self.tmpfiles.read_bytes() != PROXY_TMPFILES:
            raise ValueError('Conflicting qacey-dev-proxy tmpfiles rule. Review it before preparing the gateway.')
        existing = web.trusted(self.record, optional=True)
        previous = web.parse_json(self.record.read_text()) if existing else None
        if previous is not None:
            if (not isinstance(previous, dict) or previous.get('schema') != 1
                    or any(previous.get(k) != identity[k] for k in ('user', 'uid', 'gid', 'home'))):
                raise ValueError('Gateway installation belongs to a different development account.')
            web.verify_files(self.directory, previous, pending=previous.get('ready') is not True, upgrade=True)
        for path in (self.directory, self.lib):
            if web.trusted(path, directory=True, optional=True) and previous is None:
                raise ValueError('Refusing an unrelated gateway installation directory.')
        for path in (self.launcher, *(self.lib / name for name in LIB_FILES)):
            web.trusted_parents(path, HOST_ROOT, optional=True)
            if web.trusted(path, optional=True) and previous is None:
                raise ValueError('Refusing an unrelated gateway helper.')
        # Preparing assets never requires or reads credentials. Check metadata only if present.
        for path in (self.directory / 'oauth2.env', self.directory.parent / 'openchamber.env'):
            info = web.trusted(path, optional=True)
            if info and info.st_mode & 0o777 != 0o600:
                raise ValueError('Existing gateway/native secrets must be root-owned mode 0600.')
        files = web.render(self.settings, identity, web.read_versions(ROOT / 'versions.env'), ASSETS / 'web')
        record = dict(schema=1, ready=False, settings=self.settings, files=web.hashes(files),
                      **{k: identity[k] for k in ('user', 'uid', 'gid', 'home')})
        if previous:
            record['previous_files'] = previous['files']
            if previous.get('ready') is not True:
                # Finish the same interrupted publication; a new requested version must wait.
                if any(record['files'][name] != digest for name, digest in previous['files'].items()):
                    raise ValueError('Finish the interrupted gateway version before preparing a different one.')
                record['previous_files'] = previous.get('previous_files', {})
        return record, files

    def apply(self):
        self.preflight()  # No lock object is created until the read-only checks succeed.
        with web.gateway_lock(HOST_ROOT, create=True):
            record, files = self.preflight()
            record['source_version'] = source_version()
            self.directory.mkdir(mode=0o755, exist_ok=True)
            write_atomic(self.record, (json.dumps(record, indent=2) + '\n').encode())
            for name, data in files.items(): write_atomic(self.directory / name, data)
            self.lib.mkdir(mode=0o755, exist_ok=True)
            for name in LIB_FILES: write_atomic(self.lib / name, (ASSETS / name).read_bytes())
            write_atomic(self.launcher, (ASSETS / 'qacey-dev-web').read_bytes(), 0o755)
            self.tmpfiles.parent.mkdir(mode=0o755, exist_ok=True)
            write_atomic(self.tmpfiles, PROXY_TMPFILES)
            record['ready'] = True
            record.pop('previous_files', None)
            write_atomic(self.record, (json.dumps(record, indent=2) + '\n').encode())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--settings', type=Path, required=True, help='nonsecret JSON; see web/settings.example.json')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and os.geteuid() != ROOT_UID: raise PermissionError('Root is required to install gateway assets.')
    provision = Provision(web.parse_json(args.settings.read_text()))
    record, _ = provision.preflight()
    print(f"Gateway: https://{record['settings']['hostname']}\nProject: qacey-dev-web\nAccount: {record['user']}")
    if args.apply:
        provision.apply()
        print('Gateway files prepared. No credentials, containers or services were created or started.')
    else:
        print('Dry run. Pass --apply as root to prepare gateway files.')
    return 0


if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc: sys.exit(f'Gateway preparation: {exc}')
