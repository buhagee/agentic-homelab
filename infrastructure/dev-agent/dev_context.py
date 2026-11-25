"""Account boundaries, private configuration and installed runtime selection."""

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import mcp_config
import sync_config

ASSETS = Path(__file__).resolve().parent
RECORD = Path('/etc/qacey-dev/installation.json')
ROOT_UID = 0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


foundation_path = (ASSETS.parent / 'codex/codex_account.py'
                   if ASSETS.name == 'dev-agent' and ASSETS.parent.name == 'infrastructure'
                   else ASSETS.parent / 'qacey-codex/codex_account.py')
foundation = load_module('qacey_development_foundation', foundation_path)


def current():
    account = foundation.current_account()
    info = RECORD.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID
            or info.st_mode & 0o022 or info.st_nlink != 1):
        raise ValueError('Untrusted development installation record.')
    record = mcp_config.parse_json(RECORD.read_text(), 'development installation record')
    identity = (record.get('user'), record.get('home'), record.get('uid'), record.get('gid'))
    if (record.get('schema') != 1 or record.get('ready') is not True
            or identity != (account.user, str(account.home), os.geteuid(), os.getegid())):
        raise ValueError('Development provisioning is incomplete or differs from the current account.')
    if type(record.get('port')) is not int or not 1024 <= record['port'] <= 65535:
        raise ValueError('Invalid recorded web port.')
    node = record.get('node')
    if not isinstance(node, str) or not Path(node).is_absolute() or str(Path(node)) != node or '..' in Path(node).parts:
        raise ValueError('Invalid recorded Node executable.')
    return account, record


def private_path(home, path, *, directory=False, optional=False, create=False):
    """Check every user-owned component without following directory symlinks."""
    if not path.is_relative_to(home) or path == home:
        raise ValueError('Private path must be below the development home.')
    parts = path.relative_to(home).parts
    current_path = home
    for index, part in enumerate(parts):
        current_path /= part
        is_directory = index < len(parts) - 1 or directory
        try:
            info = current_path.lstat()
        except FileNotFoundError:
            if create and is_directory:
                current_path.mkdir(mode=0o700)
                info = current_path.lstat()
            elif optional:
                return None
            else:
                raise
        expected = stat.S_ISDIR if is_directory else stat.S_ISREG
        if (not expected(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022
                or (not is_directory and info.st_nlink != 1)):
            raise ValueError(f'Unexpected owner, type or permissions: {current_path}')
    return info


RESERVED = {'HOME', 'USER', 'LOGNAME', 'PATH', 'SHELL', 'ENV', 'BASH_ENV', 'IFS',
            'CDPATH', 'GLOBIGNORE', 'SHELLOPTS', 'BASHOPTS', 'TMUX', 'TMPDIR', 'TMP', 'TEMP', 'SSH_AUTH_SOCK',
            'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY',
            'AZURE_OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'XAI_API_KEY', 'DEEPSEEK_API_KEY',
            'MISTRAL_API_KEY', 'GROQ_API_KEY', 'COHERE_API_KEY', 'TOGETHER_API_KEY',
            'FIREWORKS_API_KEY', 'ZAI_API_KEY', 'CEREBRAS_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS'}
RESERVED_PREFIXES = ('LD_', 'DYLD_', 'PYTHON', 'NODE_', 'NPM_', 'npm_', 'BASH_', 'LC_',
                     'CODEX_', 'OPENCODE_', 'OPENCHAMBER_', 'XDG_', 'GIT_', 'SSL_', 'OPENSSL_',
                     'OPENAI_', 'ANTHROPIC_', 'AWS_', 'AZURE_', 'GOOGLE_CLOUD_', 'GCLOUD_')


def environment(account, *, persistent=False, tmux_client=False):
    names = sync_config.managed_env_names(account.home)
    env = account.environment()
    if any(name in RESERVED or name in env or name.startswith(RESERVED_PREFIXES) for name in names):
        raise ValueError('Shared MCP environment contains a reserved process/provider variable; use a dedicated MCP variable name.')
    values = {}
    path = account.home / '.config/qacey-dev/mcp-env.json'
    info = private_path(account.home, path, optional=True)
    if info is not None:
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('MCP environment file must have mode 0600.')
        values = mcp_config.parse_json(path.read_text(), 'private MCP environment')
        if (not isinstance(values, dict) or set(values) - names
                or any(not isinstance(value, str) or '\x00' in value for value in values.values())):
            raise ValueError('Private MCP environment contains undeclared names or invalid values.')
    if tmux_client:
        missing = (names & os.environ.keys()) - values.keys()
        if missing:
            raise ValueError(f"Persistent Codex sessions require shell-exported MCP names in {path} "
                             f"(mode 0600): {', '.join(sorted(missing))}")
        return env
    if not persistent:
        env.update({name: os.environ[name] for name in names if name in os.environ})
    env.update(values)
    return env


def node_version(node, env, cwd):
    result = subprocess.run([str(node), '--version'], env=env, cwd=cwd,
                            capture_output=True, text=True, check=True)
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)\s*', result.stdout)
    if match is None or tuple(map(int, match.groups())) < (24, 14, 0):
        raise ValueError('OpenChamber requires Node >=24.14.0; configure --node during provisioning.')
    return tuple(map(int, match.groups()))


def runtime_selection(account, record):
    path = account.home / '.local/share/qacey-dev/runtime/installation.json'
    private_path(account.home, path)
    selected = mcp_config.parse_json(path.read_text(), 'runtime selection')
    release = json.loads((ASSETS / 'release.json').read_text())
    if any(record.get(name + '_version') != release[name]['version'] for name in ('opencode', 'openchamber')):
        raise ValueError('Provisioned and packaged runtime versions differ; refresh root helpers first.')
    env = account.environment()
    node = Path(record['node'])
    major = node_version(node, env, account.home)[0]
    base = path.parent
    expected = {
        'opencode': base / ('opencode-' + release['opencode']['version']) / 'opencode',
        'openchamber': base / f"openchamber-{release['openchamber']['version']}-node{major}",
    }
    if (selected.get('schema') != 1 or selected.get('node_major') != major
            or selected.get('node') != str(node)
            or selected.get('opencode') != str(expected['opencode'])
            or selected.get('openchamber') != str(expected['openchamber'])):
        raise ValueError('Runtime selection differs from the configured Node/release; install the reviewed runtime first.')
    private_path(account.home, expected['opencode'])
    private_path(account.home, expected['openchamber'], directory=True)
    private_path(account.home, expected['openchamber'] / 'build/bin/cli.js')
    return dict(expected, node=node)


def check_openchamber_settings(account):
    path = account.home / '.config/openchamber/settings.json'
    if private_path(account.home, path, optional=True) is not None:
        settings = mcp_config.parse_json(path.read_text(), 'OpenChamber settings')
        if not isinstance(settings, dict):
            raise ValueError('OpenChamber settings must be an object.')
        if settings.get('useGlobalOpenCodeService'):
            raise ValueError('Turn off OpenChamber shared OpenCode service mode before managed startup.')
