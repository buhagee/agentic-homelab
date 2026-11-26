import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from test_dev_launcher import ROOT, ASSETS, load


def archive(entries):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as bundle:
        for name, payload, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == 'link':
                info.type = tarfile.SYMTYPE
                info.linkname = '/outside'
                bundle.addfile(info)
            else:
                info.size = len(payload)
                info.mode = 0o755 if name == 'opencode' else 0o644
                bundle.addfile(info, io.BytesIO(payload))
    return out.getvalue()


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ASSETS / 'install_runtime.py').exists(), 'missing native runtime installer')
        self.runtime = load('test_dev_install_runtime', ASSETS / 'install_runtime.py')
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home.chmod(0o700)
        self.account = self.runtime.dev_context.foundation.Account('dev-agent', self.home)
        (self.home / '.local/bin').mkdir(parents=True, mode=0o700)
        (self.home / '.codex').mkdir(mode=0o700)
        self.record = {'node': '/usr/bin/node', 'opencode_version': '2.4.1', 'openchamber_version': '2.8.0'}
        self.assets = Path(self.enterContext(tempfile.TemporaryDirectory()))
        web = self.assets / 'runtime/openchamber'
        web.mkdir(parents=True)
        package = b'{"name":"@openchamber/web","version":"2.8.0"}\n'
        lock = b'{"lockfileVersion":3,"packages":{}}\n'
        (web / 'package.json').write_bytes(package)
        (web / 'package-lock.json').write_bytes(lock)
        self.binaries = {
            'https://example.invalid/opencode.tar.gz': archive([('opencode', b'fake-native-binary', 'file')]),
            'https://example.invalid/openchamber.tgz': archive([('package/package.json', package, 'file'),
                                                               ('package/build/bin/cli.js', b'// fixture', 'file')])}
        self.release = {'schema':1, 'opencode': {'version':'2.4.1','assets':{'x64': {'url':'https://example.invalid/opencode.tar.gz','sha256':hashlib.sha256(self.binaries['https://example.invalid/opencode.tar.gz']).hexdigest()}}},
                        'openchamber': {'version':'2.8.0','url':'https://example.invalid/openchamber.tgz',
                                        'sha256':hashlib.sha256(self.binaries['https://example.invalid/openchamber.tgz']).hexdigest(),
                                        'manifest_sha256':hashlib.sha256(package).hexdigest(), 'lock_sha256':hashlib.sha256(lock).hexdigest()}}
        (self.assets / 'release.json').write_text(json.dumps(self.release))
        self.enterContext(patch.object(self.runtime, 'ASSETS', self.assets))
        self.enterContext(patch.object(self.runtime.platform, 'machine', return_value='x86_64'))
        self.downloads = []
        def open_url(url, **kwargs):
            self.downloads.append(url)
            return io.BytesIO(self.binaries[url])
        self.enterContext(patch.object(self.runtime, 'urlopen', side_effect=open_url))
        self.commands = []
        def run(argv, **kwargs):
            self.commands.append((argv, kwargs))
            if argv[0] == '/usr/bin/npm':
                env = kwargs['env']
                self.assertNotEqual(env['NPM_CONFIG_USERCONFIG'], env['NPM_CONFIG_GLOBALCONFIG'])
                self.assertEqual(Path(env['NPM_CONFIG_USERCONFIG']).read_text(), '')
                self.assertEqual(Path(env['NPM_CONFIG_GLOBALCONFIG']).read_text(), '')
            if argv[1:] == ['--version'] and argv[0] == '/usr/bin/node': output='v24.22.3\n'
            elif argv[-1] == '--version' and argv[0].endswith('/opencode'): output='opencode v2.4.1\n'
            elif argv[-1] == '--version': output='2.8.0\n'
            else: output=''
            return subprocess.CompletedProcess(argv, 0, output, '')
        self.enterContext(patch.object(subprocess, 'run', side_effect=run))
        self.enterContext(patch.object(self.runtime.shutil, 'which', return_value='/usr/bin/npm'))
        self.enterContext(redirect_stdout(io.StringIO()))

    def test_dry_run_does_not_download_execute_or_write(self):
        before = list(self.home.rglob('*'))
        self.runtime.install(self.account, self.record, False)
        self.assertEqual(list(self.home.rglob('*')), before)
        self.assertFalse(self.downloads)
        self.assertFalse(self.commands)

    def test_verified_install_publishes_after_both_versions_pass_and_repeats_without_download(self):
        self.runtime.install(self.account, self.record, True)
        base = self.home / '.local/share/qacey-dev/runtime'
        selected = json.loads((base / 'installation.json').read_text())
        self.assertEqual(selected['node_major'], 24)
        self.assertTrue(Path(selected['openchamber']).name.endswith('-node24'))
        self.assertEqual((self.home / '.local/bin/opencode').resolve(), Path(selected['opencode']))
        self.assertEqual(len(self.downloads), 2)
        npm = [argv for argv, _ in self.commands if argv[0] == '/usr/bin/npm'][0]
        self.assertIn('ci', npm)
        self.assertIn('--omit=dev', npm)
        self.assertIn('--foreground-scripts', npm)
        self.assertNotIn('--ignore-scripts', npm)
        self.runtime.install(self.account, self.record, True)
        self.assertEqual(len(self.downloads), 2)

    def test_hash_mismatch_never_publishes_launchers(self):
        self.binaries['https://example.invalid/opencode.tar.gz'] = b'wrong asset'
        with self.assertRaises(ValueError): self.runtime.install(self.account, self.record, True)
        self.assertFalse((self.home / '.local/bin/opencode').exists())
        self.assertFalse((self.home / '.local/share/qacey-dev/runtime/installation.json').exists())

    def test_unrelated_binary_or_symlinked_runtime_parent_refused_before_download(self):
        binary = self.home / '.local/bin/opencode'
        binary.write_text('existing manual install')
        with self.assertRaises(ValueError): self.runtime.install(self.account, self.record, True)
        self.assertEqual(binary.read_text(), 'existing manual install')
        self.assertFalse(self.downloads)
        binary.unlink()
        (self.home / '.local/share').symlink_to(self.assets)
        with self.assertRaises(ValueError): self.runtime.install(self.account, self.record, True)
        self.assertFalse(self.downloads)

    def test_tar_traversal_links_duplicate_paths_and_unexpected_binary_are_rejected(self):
        for entries in ([('../escape', b'x', 'file')], [('package/evil','', 'link')],
                        [('package/a',b'x','file'),('package/a',b'y','file')], [('different',b'x','file')]):
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                payload = base / 'archive.tgz'
                payload.write_bytes(archive(entries))
                with self.assertRaises(ValueError): self.runtime.extract(payload, base / 'out', 'opencode' if entries[0][0]=='different' else 'openchamber')
                self.assertFalse((base / 'escape').exists())

    def test_lock_tampering_and_wrong_account_versions_fail_before_npm(self):
        (self.assets / 'runtime/openchamber/package-lock.json').write_text('changed')
        with self.assertRaises(ValueError): self.runtime.install(self.account, self.record, True)
        self.assertFalse(self.commands)
        self.assertFalse(self.downloads)
        self.record['opencode_version'] = 'other'
        with self.assertRaises(ValueError): self.runtime.install(self.account, self.record, False)

    def test_root_and_unsupported_machine_fail_before_download(self):
        with patch.object(os, 'geteuid', return_value=0), self.assertRaises(PermissionError):
            self.runtime.install(self.account, self.record, True)
        with patch.object(self.runtime.platform, 'machine', return_value='unsupported'), self.assertRaises(ValueError):
            self.runtime.install(self.account, self.record, True)
        self.assertFalse(self.downloads)

    def test_native_addon_failure_prevents_publication_and_retry_reuses_verified_binary(self):
        previous = subprocess.run.side_effect
        def fail_native(argv, **kwargs):
            if argv[-1] == "require('node-pty')":
                raise subprocess.CalledProcessError(1, argv)
            return previous(argv, **kwargs)
        with patch.object(subprocess, 'run', side_effect=fail_native), self.assertRaises(subprocess.CalledProcessError):
            self.runtime.install(self.account, self.record, True)
        self.assertFalse((self.home / '.local/bin/opencode').exists())
        self.assertFalse((self.home / '.local/share/qacey-dev/runtime/installation.json').exists())
        self.runtime.install(self.account, self.record, True)
        self.assertEqual(self.downloads.count('https://example.invalid/opencode.tar.gz'), 1)
        self.assertEqual(self.downloads.count('https://example.invalid/openchamber.tgz'), 2)

    def test_concurrent_binary_edit_is_preserved_before_publication(self):
        previous = subprocess.run.side_effect
        def change_binary(argv, **kwargs):
            if argv[-1] == "require('node-pty')":
                (self.home / '.local/bin/opencode').write_text('manual replacement')
            return previous(argv, **kwargs)
        with patch.object(subprocess, 'run', side_effect=change_binary), self.assertRaises(ValueError):
            self.runtime.install(self.account, self.record, True)
        self.assertEqual((self.home / '.local/bin/opencode').read_text(), 'manual replacement')
        self.assertFalse((self.home / '.local/share/qacey-dev/runtime/installation.json').exists())

    def test_reviewed_native_release_assets_and_lock_hashes(self):
        release = json.loads((ASSETS / 'release.json').read_text())
        opencode = release['opencode']
        self.assertRegex(opencode['version'], r'^\d+\.\d+\.\d+$')
        self.assertEqual(set(opencode['assets']), {'x64', 'arm64'})
        for arch, asset in opencode['assets'].items():
            self.assertEqual(asset['url'], 'https://github.com/anomalyco/opencode/releases/download/'
                             f"v{opencode['version']}/opencode-linux-{arch}.tar.gz")
            self.assertRegex(asset['sha256'], r'^[0-9a-f]{64}$')
        for name,key in (('package.json','manifest_sha256'),('package-lock.json','lock_sha256')):
            self.assertEqual(hashlib.sha256((ASSETS / 'runtime/openchamber' / name).read_bytes()).hexdigest(), release['openchamber'][key])


if __name__ == '__main__': unittest.main()
