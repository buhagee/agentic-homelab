#!/usr/bin/python3
"""Opt-in native updater. No caller paths, environment, accounts or commands are trusted.

The transaction is deliberately a small, forward-only journal. Once publication
begins, retry the recorded source and original lifecycle; never roll back mutable
application data. The timer supplies a second idle observation without sleeping.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

HOST_ROOT = Path('/')
ROOT_UID = 0
POLICY = 'etc/qacey-dev/deployment.json'
STATE = 'var/lib/qacey-dev-deploy'
LIBRARY = 'usr/local/lib/qacey-dev-deploy'
DEFAULT_REPOSITORY = 'https://github.com/buhagee/agentic-homelab.git'
APP = 'qacey-openchamber.service'
TMUX = 'qacey-codex-tmux.service'
CODEX = 'qacey-codex.service'
SOCKET = 'qacey-dev-proxy.socket'
PROXY = 'qacey-dev-proxy.service'
UNITS = (APP, TMUX, CODEX, SOCKET, PROXY)
QUIET_SECONDS = 60
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
SYSTEM_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root', 'LC_ALL': 'C'}
GIT_ENV = dict(SYSTEM_ENV, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='/bin/false', GIT_ATTR_NOSYSTEM='1',
               GIT_NO_REPLACE_OBJECTS='1')
GIT = ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'credential.helper=',
       '-c', 'core.askPass=/bin/false', '-c', 'protocol.allow=never',
       '-c', 'protocol.https.allow=always', '-c', 'http.followRedirects=false',
       '-c', 'core.autocrlf=false', '-c', 'core.fsmonitor=false']
UPDATER_FILES = ('deployment.py', 'deployment_host.py', 'deployment_probe.py', 'web_config.py')
INPUTS = (
    'scripts/setup/install-codex.py', 'scripts/setup/install-dev-agent.py',
    'scripts/setup/install-dev-web.py', 'scripts/setup/install-dev-autodeploy.py',
    *('infrastructure/codex/' + name for name in (
        'codex_account.py', 'seed_home.py', 'qacey-codex', 'qacey-codex.py',
        'install_runtime.py', 'release.json', 'config.toml.in', 'AGENTS.md.in',
        'qacey-codex.service.in')),
    *('infrastructure/dev-agent/' + name for name in (
        'qacey-dev', 'qacey-dev.py', 'dev_context.py', 'install_runtime.py',
        'release.json', 'sync_config.py', 'mcp_config.py', 'shared/AGENTS.md',
        'shared/mcp.json', 'runtime/openchamber/package.json',
        'runtime/openchamber/package-lock.json', 'qacey-codex-tmux.service.in',
        'qacey-openchamber.service.in', 'qacey-dev-proxy.socket.in',
        'qacey-dev-proxy.service.in', 'web_config.py', 'qacey-dev-web',
        'qacey-dev-web.py', 'web/compose.yml', 'web/Caddyfile.in',
        'web/oauth2-proxy.cfg.in', 'web/oracle-dev-route.yml.in',
        'qacey-dev-deploy', *UPDATER_FILES[:-1])),
)


class Blocked(RuntimeError):
    """Only fixed, nonsecret reason codes may cross the broker boundary."""


def trusted(path, *, directory=False, optional=False, private=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise Blocked('trusted-file-missing') from None
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022
            or (not directory and info.st_nlink != 1)
            or (private and stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600))):
        raise Blocked('untrusted-file-owner-mode-or-link')
    return info


def parents(path, *, optional=False):
    for parent in reversed(path.parents):
        if parent.is_relative_to(HOST_ROOT):
            trusted(parent, directory=True, optional=optional)


def json_load(path, *, private=False):
    parents(path)
    trusted(path, private=private)
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Blocked('duplicate-json-key')
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(), object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise Blocked('invalid-json-record') from None


def atomic(path, data, mode=0o600):
    parents(path)
    trusted(path, optional=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def save(path, value):
    atomic(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def repository(value):
    if not isinstance(value, str):
        raise Blocked('repository-must-be-reviewed-https-github')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment
            or not re.fullmatch(r'/[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*', parsed.path)):
        raise Blocked('repository-must-be-reviewed-https-github')
    return value


def load_policy():
    path = HOST_ROOT / POLICY
    # A missing opt-in must not even create a lock, source, or state directory.
    parents(path, optional=True)
    if trusted(path, optional=True) is None:
        return None
    value = json_load(path, private=True)
    keys = {'schema', 'repository', 'branch', 'operator', 'user', 'uid', 'gid', 'home',
            'port', 'node', 'gateway', 'verified_oracle_route'}
    if (not isinstance(value, dict) or set(value) != keys or value.get('schema') != 1
            or value.get('branch') != 'main' or not DIGEST.fullmatch(str(value.get('verified_oracle_route', '')))
            or any(type(value.get(k)) is not int or value[k] <= 0 or value[k] == 65532 for k in ('uid', 'gid'))
            or any(not isinstance(value.get(k), str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', value[k])
                   or value[k] == 'root' for k in ('user', 'operator'))
            or value['user'] == value['operator']
            or type(value.get('port')) is not int or not 1024 <= value['port'] <= 65535):
        raise Blocked('invalid-deployment-policy')
    for key in ('home', 'node'):
        raw = value[key]
        if (not isinstance(raw, str) or not Path(raw).is_absolute() or str(Path(raw)) != raw
                or '..' in Path(raw).parts or any(not c.isprintable() for c in raw)):
            raise Blocked('invalid-deployment-policy')
    repository(value['repository'])
    return value


@contextmanager
def deployment_lock():
    directory = HOST_ROOT / STATE
    parents(directory)
    trusted(directory, directory=True, private=True)
    path = directory / 'deployment.lock'
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        trusted(path, private=True)
        fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size):
            raise Blocked('invalid-deployment-lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('another-native-deployment-is-running') from None
        if not os.path.samestat(info, path.lstat()):
            raise Blocked('deployment-lock-changed')
        yield
    finally:
        os.close(fd)


def run(command, label, *, identity=None, check=True, timeout=300, env=None, cwd=None, input=None):
    """Capture every child byte; never interpolate child text in errors or logs."""
    kwargs = dict(env=dict(SYSTEM_ENV if env is None else env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                  text=True, cwd=cwd, start_new_session=True)
    if identity is not None:
        kwargs.update(user=identity['uid'], group=identity['gid'], extra_groups=[], umask=0o077,
                      cwd=identity['home'], env=dict(SYSTEM_ENV, HOME=identity['home'],
                                                   USER=identity['user'], LOGNAME=identity['user']))
    child = None
    def terminate_group():
        if child is None:
            return
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # The parent can exit before a grandchild. Terminate the entire
            # exclusively owned group even when communicate already returned.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            child.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            # A deliberately detached process must not hold our pipe open forever.
            # The known installer tree is synchronous and does not daemonize.
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
            child.wait(timeout=3)
    try:
        child = subprocess.Popen(command, **kwargs)
        stdout, stderr = child.communicate(input=input, timeout=timeout)
        result = subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
    except (OSError, subprocess.SubprocessError):
        terminate_group()
        raise Blocked(label + '-failed') from None
    except BaseException:
        terminate_group()
        raise
    # A successful synchronous helper must not leave background installer writers
    # racing the next transaction. Service/container starts occur in their owning
    # managers, outside this CLI process group, and are unaffected.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if check and result.returncode:
        raise Blocked(label + '-failed')
    return result


def load_module(name, path):
    parents(path)
    trusted(path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Source:
    """Independent root Git source; remote configuration is never read from a checkout."""
    def __init__(self, policy):
        self.policy = policy
        self.base = HOST_ROOT / STATE
        self.gitdir = self.base / 'repository.git'

    def git(self, args, *, local=False, check=True):
        command = [*GIT, *(['-c', 'protocol.file.allow=always'] if local else []), *args]
        home = self.base / 'git-home'
        parents(home)
        if trusted(home, directory=True, optional=True, private=True) is None:
            home.mkdir(mode=0o700)
        # An empty private HOME also excludes root's .netrc and XDG config.
        return run(command, 'trusted-source', env=dict(GIT_ENV, HOME=str(home), XDG_CONFIG_HOME=str(home)),
                   check=check, timeout=180)

    def tree_trusted(self, path):
        parents(path)
        trusted(path, directory=True)
        # Reject symlinks, hardlinks and writable Git metadata as well as payloads.
        for item in path.rglob('*'):
            trusted(item, directory=item.is_dir() and not item.is_symlink())

    def fetch(self, revision):
        if not SHA.fullmatch(revision):
            raise Blocked('invalid-revision')
        parents(self.gitdir)
        if trusted(self.gitdir, directory=True, optional=True) is None:
            self.git(['init', '--bare', '--template=', str(self.gitdir)])
        self.tree_trusted(self.gitdir)
        self.git(['--git-dir', str(self.gitdir), 'fetch', '--force', '--no-tags', '--no-recurse-submodules',
                  '--', self.policy['repository'], '+refs/heads/main:refs/heads/main'])
        tip = self.git(['--git-dir', str(self.gitdir), 'rev-parse', '--verify', 'refs/heads/main^{commit}']).stdout.strip()
        if tip != revision:
            raise Blocked('requested-revision-is-not-current-main')
        return revision

    def descendant(self, previous, revision):
        if previous and previous != revision:
            result = self.git(['--git-dir', str(self.gitdir), 'merge-base', '--is-ancestor', previous, revision], check=False)
            if result.returncode:
                raise Blocked('non-forward-native-revision-requires-review')

    def checkout(self, revision, *, recovery=False):
        path = self.base / 'sources' / revision
        parents(path, optional=True)
        if trusted(path, directory=True, optional=True) is None:
            if recovery:
                raise Blocked('interrupted-source-missing-fix-forward-required')
            path.parent.mkdir(mode=0o700, exist_ok=True)
            # A failed fetch/check-out never occupies the immutable final name.
            # SIGKILL may leave an unused private staging directory; it is never
            # mistaken for a verified target or executed during a retry.
            with tempfile.TemporaryDirectory(dir=path.parent, prefix='.prepare-') as temporary:
                candidate = Path(temporary)
                self.git(['init', '--template=', str(candidate)])
                self.git(['-C', str(candidate), 'fetch', '--no-tags', '--no-recurse-submodules',
                          '--', str(self.gitdir), revision], local=True)
                self.git(['-C', str(candidate), 'checkout', '--detach', '--force', revision])
                self.tree_trusted(candidate)
                if (self.git(['-C', str(candidate), 'rev-parse', '--verify', 'HEAD^{commit}']).stdout.strip() != revision
                        or self.git(['-C', str(candidate), 'status', '--porcelain', '--untracked-files=all']).stdout):
                    raise Blocked('trusted-source-staging-verification-failed')
                candidate.rename(path)
        self.tree_trusted(path)
        actual = self.git(['-C', str(path), 'rev-parse', '--verify', 'HEAD^{commit}']).stdout.strip()
        changes = self.git(['-C', str(path), 'status', '--porcelain', '--untracked-files=all']).stdout
        if actual != revision or changes:
            raise Blocked('trusted-source-revision-or-files-changed')
        # The verified worker for this revision validates its own input list.
        # Future revisions can retire files that this worker still knows about.
        return path


def fingerprint(source, policy, *, legacy=False):
    digest = hashlib.sha256()
    inputs = set(INPUTS)
    if not legacy:
        inputs.discard('scripts/setup/install-dev-autodeploy.py')
        inputs.difference_update('infrastructure/dev-agent/' + name
                                 for name in ('qacey-dev-deploy', *UPDATER_FILES[:-1]))
    for relative in sorted(inputs):
        path = source / relative
        parents(path)
        trusted(path)
        digest.update(relative.encode() + b'\0' + path.read_bytes() + b'\0')
    web = load_module('qacey_candidate_web_config', source / 'infrastructure/dev-agent/web_config.py')
    selections = {key: policy[key] for key in ('user', 'uid', 'gid', 'home', 'port', 'node', 'gateway', 'verified_oracle_route')}
    selections['versions'] = web.read_versions(source / 'versions.env')
    digest.update(json.dumps(selections, sort_keys=True, separators=(',', ':')).encode())
    return digest.hexdigest()


def install_updater_assets(assets, *, trusted_source=True):
    """Publish a complete helper version, then atomically change the entry point.

    Old helper versions remain available. An interrupted copy cannot mix module
    versions in the next process, or replace the permanent policy/state/lock.
    """
    directory = HOST_ROOT / LIBRARY
    parents(directory)
    trusted(directory, directory=True)
    payloads = {}
    for name in UPDATER_FILES:
        path = assets / name
        if trusted_source:
            parents(path)
            trusted(path)
        payloads[name] = path.read_bytes()
    digest = hashlib.sha256(b''.join(name.encode() + b'\0' + payloads[name] for name in UPDATER_FILES)).hexdigest()
    release = directory / 'releases' / digest
    parents(release, optional=True)
    for path in (release.parent, release):
        if trusted(path, directory=True, optional=True) is None:
            path.mkdir(mode=0o755)
        path.chmod(0o755)
    for name, data in payloads.items():
        path = release / name
        if trusted(path, optional=True) is not None and path.read_bytes() != data:
            raise Blocked('installed-updater-version-drifted')
        if not path.exists():
            atomic(path, data, 0o644)
    launcher_path = assets / 'qacey-dev-deploy'
    if trusted_source:
        parents(launcher_path)
        trusted(launcher_path)
    launcher = launcher_path.read_bytes()
    original = b'/usr/local/lib/qacey-dev-deploy/deployment.py'
    executable = ('/usr/local/lib/qacey-dev-deploy/releases/' + digest + '/deployment.py').encode()
    if launcher.count(original) != 1:
        raise Blocked('invalid-native-updater-launcher')
    target = HOST_ROOT / 'usr/local/sbin/qacey-dev-deploy'
    parents(target)
    data = launcher.replace(original, executable)
    if trusted(target, optional=True) is not None and target.read_bytes() == data:
        return False
    atomic(target, data, 0o755)
    return True


def refresh_updater(source):
    assets = source / 'infrastructure/dev-agent'
    compat = json_load(assets / 'updater-compat.json')
    if (compat != {'launcher': 1, 'policy': 1, 'state': 1}
            or any(type(value) is not int for value in compat.values())):
        raise Blocked('incompatible-helper-requires-explicit-enrollment')
    return install_updater_assets(assets)


def empty_state():
    return dict(schema=1, desired_revision=None, desired_digest=None, applied_revision=None,
                applied_digest=None, status='ready', reason='not-applied', quiet=None,
                transaction=None, managed_files={}, paused=False)


def load_state():
    path = HOST_ROOT / STATE / 'state.json'
    value = json_load(path, private=True)
    if (not isinstance(value, dict) or set(value) != set(empty_state()) or value.get('schema') != 1
            or type(value.get('paused')) is not bool):
        raise Blocked('invalid-native-state')
    for key, pattern in (('desired_revision', SHA), ('applied_revision', SHA),
                         ('desired_digest', DIGEST), ('applied_digest', DIGEST)):
        if value[key] is not None and (not isinstance(value[key], str) or not pattern.fullmatch(value[key])):
            raise Blocked('invalid-native-state')
    transaction = value['transaction']
    if transaction is not None:
        required = {'revision', 'digest', 'phase', 'original', 'credentials'}
        if (not isinstance(transaction, dict) or set(transaction) != required
                or not SHA.fullmatch(str(transaction['revision'])) or not DIGEST.fullmatch(str(transaction['digest']))
                or transaction['phase'] not in ('prepared', 'quiescing', 'publishing', 'starting', 'restoring')
                or not isinstance(transaction['original'], dict) or not isinstance(transaction['credentials'], dict)):
            raise Blocked('invalid-native-transaction')
    return value


class Deployment:
    def __init__(self, policy, host, source=None, *, clock=time.time):
        self.policy, self.host = policy, host
        self.source = source if source is not None else Source(policy)
        self.clock = clock
        self.state = load_state()

    def persist(self):
        save(HOST_ROOT / STATE / 'state.json', self.state)

    def pending(self, reason, *, reset=True):
        self.state.update(status='pending', reason=reason)
        if reset:
            self.state['quiet'] = None
        self.persist()
        return 0

    def apply(self, requested):
        try:
            return self._apply(requested)
        except Exception as exc:
            reason = str(exc) if isinstance(exc, Blocked) else 'fix-forward-or-local-review-required'
            self.state.update(status='failed', reason=reason, quiet=None)
            self.persist()
            raise

    def _apply(self, requested):
        if not SHA.fullmatch(requested):
            raise Blocked('invalid-revision')
        if self.state['paused']:
            return self.pending('operator-paused')
        transaction = self.state['transaction']
        if transaction is not None:
            # Only the exact, previously verified journal target may bypass a new
            # remote-tip check. A new caller revision must still be current main.
            if requested != transaction['revision']:
                self.source.fetch(requested)
            source = self.source.checkout(transaction['revision'], recovery=True)
            # The previous worker could switch launchers mid-publication. Read
            # its exact journal digest without rewriting the saved transaction.
            if (fingerprint(source, self.policy) != transaction['digest']
                    and fingerprint(source, self.policy, legacy=True) != transaction['digest']):
                raise Blocked('interrupted-source-or-policy-changed')
            self.host.close_ingress(transaction['original'])
            self.host.check_records(recovery=True)
            if self.host.credentials() != transaction['credentials']:
                raise Blocked('credentials-changed-during-interrupted-update')
            return self.finish(source, recovering=True)
        self.source.fetch(requested)
        self.source.descendant(self.state['applied_revision'], requested)
        source = self.source.checkout(requested)
        if refresh_updater(source):
            # Do not create a journal with code from the superseded worker.
            # The next reconcile enters via the newly published launcher.
            return self.pending('helper-refreshed')
        self.host.check_records()
        credentials = self.host.credentials()
        self.host.verify_managed(self.state['managed_files'])
        digest = fingerprint(source, self.policy)
        self.state.update(desired_revision=requested, desired_digest=digest)
        self.persist()
        if digest == self.state['applied_digest']:
            self.state.update(status='unchanged', reason='inputs-unchanged-no-repair-attempted', quiet=None)
            self.persist()
            return 0
        self.host.preflight(source)
        original = self.host.snapshot()
        observation = self.host.activity(original)
        if observation['state'] != 'idle':
            return self.pending(observation['reason'])
        identity = self.host.process_identity(original)
        now = self.clock()
        quiet = self.state['quiet']
        if (not isinstance(quiet, dict) or quiet.get('digest') != digest or quiet.get('identity') != identity
                or type(quiet.get('since')) not in (float, int) or now < quiet['since']):
            self.state['quiet'] = dict(digest=digest, identity=identity, since=now)
            return self.pending('quiet-observation-required', reset=False)
        if now - quiet['since'] < QUIET_SECONDS:
            return self.pending('quiet-observation-required', reset=False)
        # This original snapshot precedes stopping the socket/app (BindsTo).
        self.state['transaction'] = dict(revision=requested, digest=digest, phase='prepared',
                                         original=original, credentials=credentials)
        self.persist()
        return self.finish(source, recovering=False)

    def finish(self, source, *, recovering):
        transaction = self.state['transaction']
        original = transaction['original']
        try:
            self.host.close_ingress(original)
            if transaction['phase'] in ('prepared', 'quiescing'):
                transaction['phase'] = 'quiescing'
                self.persist()
                current = self.host.snapshot(ingress_closed=True)
                if self.host.process_identity(current) != self.host.process_identity(original):
                    observation = {'state': 'unknown', 'reason': 'application-process-changed'}
                else:
                    observation = self.host.activity(current)
                if observation['state'] != 'idle':
                    # Publication has not begun: restore only the saved ingress.
                    self.host.restore_ingress(original)
                    self.state['transaction'] = None
                    return self.pending(observation['reason'])
                if self.host.credentials() != transaction['credentials']:
                    raise Blocked('credentials-changed-before-publication')
                transaction['phase'] = 'publishing'
                self.persist()
            if transaction['phase'] == 'publishing':
                # On recovery, do not overwrite the original intent with currently
                # stopped units. A live app must still pass activity admission.
                current = self.host.snapshot(ingress_closed=True)
                observation = self.host.activity(current, recovery=True)
                if observation['state'] != 'idle':
                    if not recovering:
                        self.host.restore_ingress(original)
                        self.state['transaction'] = None
                        return self.pending(observation['reason'])
                    return self.pending('interrupted-update-' + observation['reason'])
                if current['units'][APP]['active'] and not original['units'][APP]['active']:
                    raise Blocked('stopped-application-was-started-during-update')
                self.host.stop_app(current)
                self.host.publish(source)
                self.host.install_runtime_and_sync()
                self.host.reload_units()
                transaction['phase'] = 'starting'
                self.persist()
            if transaction['phase'] in ('starting', 'restoring'):
                self.host.restore_app(original)
                self.host.health(original)
                transaction['phase'] = 'restoring'
                self.persist()
                self.host.restore_ingress(original)
                self.host.verify_restored(original)
            self.state.update(applied_revision=transaction['revision'], applied_digest=transaction['digest'],
                              status='applied', reason='verified', transaction=None, quiet=None,
                              managed_files=self.host.managed_files())
            self.persist()
            return 0
        except BaseException:
            # Never reopen ingress or roll mutable runtime/data back after a failed
            # publication/start. Persisted original state is the recovery authority.
            try:
                self.host.close_ingress(original)
            except Exception:
                pass
            self.state.update(status='failed', reason='fix-forward-retry-required', quiet=None)
            self.persist()
            raise


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # sudo-rs matches a trailing wildcard. Enforce the complete delegated
    # argument vector here, before argparse handles help or option terminators.
    if argv[:1] == ['apply'] and (len(argv) != 2 or not SHA.fullmatch(argv[1])):
        raise Blocked('invalid-revision')
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('apply', allow_abbrev=False).add_argument('revision')
    commands.add_parser('status', allow_abbrev=False)
    commands.add_parser('pause', allow_abbrev=False)
    commands.add_parser('resume', allow_abbrev=False)
    args = parser.parse_args(argv)
    if os.geteuid() != ROOT_UID:
        raise Blocked('root-required')
    policy = load_policy()
    if policy is None:
        print('Native development deployment: not-enrolled (no changes).')
        return 0
    if args.action == 'status':
        state = load_state()
        result = {key: state[key] for key in ('status', 'reason', 'desired_revision',
                  'desired_digest', 'applied_revision', 'applied_digest', 'paused')}
        result['transaction_phase'] = state['transaction']['phase'] if state['transaction'] else None
        print(json.dumps(result, sort_keys=True))
        return 0
    with deployment_lock():
        if args.action in ('pause', 'resume'):
            state = load_state()
            state.update(paused=args.action == 'pause', quiet=None, status='pending',
                         reason='operator-paused' if args.action == 'pause' else 'awaiting-current-main-trigger')
            save(HOST_ROOT / STATE / 'state.json', state)
            print('Native development deployment: ' + state['reason'] + '.')
            return 0
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        sys.modules['deployment'] = sys.modules[__name__]
        from deployment_host import Host
        controller = Deployment(policy, Host(policy))
        result = controller.apply(args.revision)
        print('Native development deployment: ' + controller.state['status'] + ' (' + controller.state['reason'] + ').')
        return result


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise Blocked('native-deployment-interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        sys.exit(main())
    except Blocked as exc:
        sys.exit('Native development deployment: ' + str(exc))
    except Exception:
        # Unexpected parser/filesystem/child failures can contain credentials.
        sys.exit('Native development deployment: failed; inspect locally and retry the recorded transaction.')
