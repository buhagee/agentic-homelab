"""Install verified OpenCode/OpenChamber releases without root or service changes."""

import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen

import dev_context

ASSETS = Path(__file__).resolve().parent
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXTRACTED = 1024 * 1024 * 1024


def atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def download(url, destination, expected):
    digest = hashlib.sha256()
    size = 0
    with urlopen(url, timeout=60) as response, destination.open('xb') as output:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > MAX_ARCHIVE:
                raise ValueError('Runtime archive exceeds the reviewed size limit.')
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != expected:
        raise ValueError('Runtime archive SHA256 differs from the reviewed release pin.')


def extract(archive, destination, package):
    """Validate the complete tar index, then write only known regular payloads."""
    with tarfile.open(archive, 'r:gz') as bundle:
        members, size = [], 0
        for member in bundle:
            members.append(member)
            size += member.size
            if len(members) > 20000 or size > MAX_EXTRACTED:
                raise ValueError('Unexpected runtime archive size or member count.')
        if not members:
            raise ValueError('Empty runtime archive.')
        names = set()
        entries = []
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or '\\' in member.name
                    or not (member.isfile() or member.isdir()) or path in names):
                raise ValueError('Unsafe or duplicate runtime archive member.')
            names.add(path)
            if package == 'opencode':
                if str(path) != 'opencode' or not member.isfile():
                    raise ValueError('Expected the sole OpenCode executable payload.')
                relative = Path('opencode')
            elif package == 'openchamber':
                if not path.parts or path.parts[0] != 'package':
                    raise ValueError('Unexpected OpenChamber archive root.')
                relative = Path(*path.parts[1:])
                if relative == Path('.') and not member.isdir():
                    raise ValueError('Unexpected package-root payload.')
            else:
                raise ValueError('Unknown runtime archive type.')
            entries.append((member, relative))
        destination.mkdir(mode=0o700)
        for member, relative in entries:
            target = destination / relative
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with target.open('xb') as out, bundle.extractfile(member) as source:
                    shutil.copyfileobj(source, out)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def marker(path, expected, account):
    info = dev_context.private_path(account.home, path, directory=True, optional=True)
    if info is None:
        return False
    file = path / '.qacey-runtime.json'
    dev_context.private_path(account.home, file)
    if dev_context.mcp_config.parse_json(file.read_text(), 'runtime ownership marker') != expected:
        raise ValueError(f'Refusing unrelated or mismatched runtime directory: {path}')
    return True


def verify(path, package, version, node, env, home):
    argv = [str(path / 'opencode'), '--version'] if package == 'opencode' else [str(node), str(path / 'build/bin/cli.js'), '--version']
    result = subprocess.run(argv, env=env, cwd=home, capture_output=True, text=True, check=True)
    expected = 'opencode v' + version if package == 'opencode' else version
    if result.stdout.strip() != expected:
        raise ValueError(f'Installed {package} version does not match the reviewed pin.')
    if package == 'openchamber':
        # --version does not necessarily load the native terminal addon. Check
        # that its compiled binding loads under this Node before publication.
        subprocess.run([str(node), '-e', "require('node-pty')"], env=env, cwd=path,
                       capture_output=True, text=True, check=True)


def snapshot(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return ('link', info.st_uid, os.readlink(path))
    if stat.S_ISREG(info.st_mode):
        return ('file', info.st_uid, hashlib.sha256(path.read_bytes()).hexdigest())
    raise ValueError(f'Unexpected runtime publication target: {path}')


def install(account, record, apply=False):
    if os.geteuid() == 0:
        raise PermissionError('Install native runtimes as the dedicated development account, never root.')
    release = json.loads((ASSETS / 'release.json').read_text())
    for name in ('opencode', 'openchamber'):
        if record.get(name + '_version') != release[name]['version']:
            raise ValueError('Provisioned and packaged runtime versions differ; refresh root helpers first.')
    machine = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    if machine not in release['opencode']['assets'] or platform.system() != 'Linux' or platform.libc_ver()[0] != 'glibc':
        raise ValueError('These reviewed native assets support glibc Linux x64/arm64 only.')
    assets = ASSETS / 'runtime/openchamber'
    for name, key in (('package.json', 'manifest_sha256'), ('package-lock.json', 'lock_sha256')):
        if hashlib.sha256((assets / name).read_bytes()).hexdigest() != release['openchamber'][key]:
            raise ValueError('Reviewed OpenChamber manifest or lockfile checksum differs.')
    base = account.home / '.local/share/qacey-dev/runtime'
    dev_context.private_path(account.home, base, directory=True, optional=True)
    dev_context.private_path(account.home, account.bin_dir, directory=True)
    selected_file = base / 'installation.json'
    selected = {}
    if dev_context.private_path(account.home, selected_file, optional=True):
        selected = dev_context.mcp_config.parse_json(selected_file.read_text(), 'runtime selection')
        if not isinstance(selected, dict) or selected.get('schema') != 1:
            raise ValueError('Invalid previous runtime selection.')
    opencode = base / ('opencode-' + release['opencode']['version'])
    binary = account.bin_dir / 'opencode'
    allowed = {str(opencode / 'opencode')}
    old = selected.get('opencode')
    if isinstance(old, str):
        path = Path(old)
        if path.name != 'opencode' or path.parent.parent != base or not path.parent.name.startswith('opencode-'):
            raise ValueError('Previous runtime selection escapes the managed directory.')
        allowed.add(old)
    try:
        existing = binary.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISLNK(existing.st_mode) or existing.st_uid != os.geteuid() or os.readlink(binary) not in allowed:
            raise ValueError('Refusing to replace an unrelated OpenCode executable.')
    before = (snapshot(binary), snapshot(selected_file))
    print(f"OpenCode {release['opencode']['version']}; OpenChamber {release['openchamber']['version']}; runtime directory: {base}")
    if not apply:
        print('Dry run. Pass --apply to verify downloads and install locked production dependencies as this user.')
        return 0
    env = account.environment()
    node = Path(record['node'])
    env['PATH'] = f"{node.parent}:{env['PATH']}"
    major = dev_context.node_version(node, env, account.home)[0]
    npm = shutil.which('npm', path=env['PATH'])
    if not npm:
        raise ValueError('npm is required alongside the configured Node executable.')
    web = base / f"openchamber-{release['openchamber']['version']}-node{major}"
    dev_context.private_path(account.home, base, directory=True, create=True)
    descriptor = os.open(base, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if (snapshot(binary), snapshot(selected_file)) != before:
            raise ValueError('Runtime selection changed; inspect it and retry the install.')
        opencode_pin = release['opencode']['assets'][machine]
        marks = {
            'opencode': dict(schema=1, package='opencode', version=release['opencode']['version'],
                             sha256=opencode_pin['sha256'], architecture=machine),
            'openchamber': dict(schema=1, package='openchamber', version=release['openchamber']['version'],
                                sha256=release['openchamber']['sha256'], lock_sha256=release['openchamber']['lock_sha256'], node_major=major),
        }
        for package, target in (('opencode', opencode), ('openchamber', web)):
            if marker(target, marks[package], account):
                verify(target, package, release[package]['version'], node, env, account.home)
                continue
            with tempfile.TemporaryDirectory(prefix='.install-', dir=base) as temporary:
                stage = Path(temporary)
                pin = opencode_pin if package == 'opencode' else release['openchamber']
                archive = stage / 'release.tgz'
                download(pin['url'], archive, pin['sha256'])
                package_dir = stage / 'payload'
                extract(archive, package_dir, package)
                if package == 'openchamber':
                    if hashlib.sha256((package_dir / 'package.json').read_bytes()).hexdigest() != pin['manifest_sha256']:
                        raise ValueError('Release package manifest differs from the reviewed lock input.')
                    shutil.copyfile(assets / 'package-lock.json', package_dir / 'package-lock.json')
                    install_env = dict(env)
                    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy',
                                 'all_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS', 'NPM_CONFIG_CAFILE'):
                        if name in os.environ: install_env[name] = os.environ[name]
                    # npm rejects loading /dev/null twice as both config types.
                    # Separate empty files also avoid the account's registry auth.
                    for name in ('npm-userconfig', 'npm-globalconfig'):
                        (stage / name).write_text('')
                    install_env.update(NPM_CONFIG_USERCONFIG=str(stage / 'npm-userconfig'),
                                       NPM_CONFIG_GLOBALCONFIG=str(stage / 'npm-globalconfig'),
                                       NPM_CONFIG_CACHE=str(stage / 'npm-cache'))
                    subprocess.run([npm, 'ci', '--omit=dev', '--foreground-scripts', '--no-audit', '--no-fund'],
                                   cwd=package_dir, env=install_env, check=True)
                verify(package_dir, package, release[package]['version'], node, env, account.home)
                atomic(package_dir / '.qacey-runtime.json', json_bytes(marks[package]))
                if target.exists() or target.is_symlink():
                    raise ValueError('Runtime destination appeared during installation; inspect it before retrying.')
                package_dir.rename(target)
        selection = dict(schema=1, node=str(node), node_major=major,
                         opencode=str(opencode / 'opencode'), openchamber=str(web))
        if (snapshot(binary), snapshot(selected_file)) != before:
            raise ValueError('Runtime selection changed during installation; no launchers were replaced.')
        if selected == selection and before[0] == ('link', os.geteuid(), selection['opencode']):
            print('Reviewed runtimes are already selected; no files or services changed.')
            return 0
        # Both packages are complete before the CLI pointer changes. Retain old
        # version directories so the operator can select a reviewed rollback.
        temporary_link = account.bin_dir / ('.qacey-opencode-' + os.urandom(8).hex())
        try:
            temporary_link.symlink_to(opencode / 'opencode')
            os.replace(temporary_link, binary)
        finally:
            temporary_link.unlink(missing_ok=True)
        atomic(selected_file, json_bytes(selection))
    finally:
        os.close(descriptor)
    print('Verified native runtimes installed. No services were started or restarted.')
    return 0
