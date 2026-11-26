#!/usr/bin/env python3
"""Refresh the reviewed OpenChamber pin in infrastructure/dev-agent after a version bump.

Usage: refresh-openchamber-release.py VERSION

Downloads the GitHub release tarball for VERSION, records its SHA-256, copies the
packaged package.json as the reviewed manifest, regenerates the lockfile with npm
(no install scripts run), and updates release.json. Run by Renovate's postUpgradeTasks;
the resulting PR is reviewed before merge.
"""
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV_AGENT = ROOT / 'infrastructure/dev-agent'
RELEASE = DEV_AGENT / 'release.json'
RUNTIME = DEV_AGENT / 'runtime/openchamber'
URL = 'https://github.com/openchamber/openchamber/releases/download/v{v}/openchamber-web-{v}.tgz'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main(argv):
    if len(argv) != 2 or not re.fullmatch(r'\d+\.\d+\.\d+', argv[1]):
        raise SystemExit('usage: refresh-openchamber-release.py MAJOR.MINOR.PATCH')
    version = argv[1]
    url = URL.format(v=version)
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = response.read()
    tarball = tempfile.NamedTemporaryFile(suffix='.tgz', delete=False)
    tarball.write(archive)
    tarball.close()
    with tarfile.open(tarball.name) as tar:
        manifest = tar.extractfile('package/package.json').read()
    if json.loads(manifest).get('version') != version:
        raise SystemExit('Release tarball package.json does not match the requested version.')
    (RUNTIME / 'package.json').write_bytes(manifest)
    subprocess.run(
        ['npm', 'install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund'],
        cwd=RUNTIME, check=True)
    release = json.loads(RELEASE.read_text())
    release['openchamber'].update(
        version=version,
        url=url,
        sha256=sha256(archive),
        manifest_sha256=sha256(manifest),
        lock_sha256=sha256((RUNTIME / 'package-lock.json').read_bytes()),
    )
    RELEASE.write_text(json.dumps(release, indent=2) + '\n')
    Path(tarball.name).unlink()
    print(f'OpenChamber pinned to {version}: tarball {release["openchamber"]["sha256"]}')


if __name__ == '__main__':
    main(sys.argv)
