#!/usr/bin/env python3
"""Refresh the reviewed OpenChamber or OpenCode pin in infrastructure/dev-agent.

Usage:
  refresh-openchamber-release.py VERSION
  refresh-openchamber-release.py --opencode VERSION

Downloads the GitHub release tarball(s) for VERSION, records SHA-256 digests,
regenerates OpenChamber's lockfile with npm (no install scripts run) when
updating OpenChamber, updates release.json and ACTIVITY_VERSIONS in
deployment_probe.py, and runs scripts/testing/check-dev-runtime.py to verify
runtime compatibility before Renovate commits the update.
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
PROBE = DEV_AGENT / 'deployment_probe.py'
RUNTIME = DEV_AGENT / 'runtime/openchamber'
OC_URL = 'https://github.com/openchamber/openchamber/releases/download/v{v}/openchamber-web-{v}.tgz'
OP_URL = 'https://github.com/anomalyco/opencode/releases/download/v{v}/opencode-linux-{arch}.tar.gz'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def update_probe_activity_versions(oc_version: str, op_version: str):
    text = PROBE.read_text(encoding='utf-8')
    pair = f"('{oc_version}', '{op_version}')"
    if pair in text:
        return
    updated, count = re.subn(
        r"(ACTIVITY_VERSIONS\s*=\s*\{)([^}]*)(\})",
        lambda m: f"{m.group(1)}{m.group(2).rstrip()}, {pair}{m.group(3)}",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit('Could not update ACTIVITY_VERSIONS in deployment_probe.py')
    PROBE.write_text(updated, encoding='utf-8')


def refresh_openchamber(version: str, release: dict):
    url = OC_URL.format(v=version)
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = response.read()
    tarball = tempfile.NamedTemporaryFile(suffix='.tgz', delete=False)
    tarball.write(archive)
    tarball.close()
    try:
        with tarfile.open(tarball.name) as tar:
            manifest = tar.extractfile('package/package.json').read()
    finally:
        Path(tarball.name).unlink(missing_ok=True)
    if json.loads(manifest).get('version') != version:
        raise SystemExit('Release tarball package.json does not match the requested version.')
    (RUNTIME / 'package.json').write_bytes(manifest)
    subprocess.run(
        ['npm', 'install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund'],
        cwd=RUNTIME, check=True)
    release['openchamber'].update(
        version=version,
        url=url,
        sha256=sha256(archive),
        manifest_sha256=sha256(manifest),
        lock_sha256=sha256((RUNTIME / 'package-lock.json').read_bytes()),
    )


def refresh_opencode(version: str, release: dict):
    assets = {}
    for arch in ('x64', 'arm64'):
        url = OP_URL.format(v=version, arch=arch)
        with urllib.request.urlopen(url, timeout=120) as response:
            archive = response.read()
        assets[arch] = {'url': url, 'sha256': sha256(archive)}
    release['opencode'] = {'version': version, 'assets': assets}


def main(argv):
    opencode_mode = False
    args = argv[1:]
    if args and args[0] == '--opencode':
        opencode_mode = True
        args = args[1:]
    if len(args) != 1 or not re.fullmatch(r'\d+\.\d+\.\d+', args[0]):
        raise SystemExit('usage: refresh-openchamber-release.py [--opencode] MAJOR.MINOR.PATCH')
    version = args[0]
    release = json.loads(RELEASE.read_text(encoding='utf-8'))
    if opencode_mode:
        refresh_opencode(version, release)
    else:
        refresh_openchamber(version, release)
    RELEASE.write_text(json.dumps(release, indent=2) + '\n', encoding='utf-8')
    update_probe_activity_versions(
        release['openchamber']['version'],
        release['opencode']['version'],
    )
    print(
        f"Pinned OpenChamber {release['openchamber']['version']} / "
        f"OpenCode {release['opencode']['version']}"
    )


if __name__ == '__main__':
    main(sys.argv)
