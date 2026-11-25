"""Root gateway validation and pure rendering; no implicit activation or secrets output."""
import base64
from contextlib import contextmanager
import fcntl
import binascii
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import stat
from urllib.parse import urlsplit

ROOT_UID = 0
SYSTEM_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root', 'LC_ALL': 'C'}
DOCKER = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock']
MANAGED = ('compose.yml', 'Caddyfile', 'oauth2-proxy.cfg', 'allowed-emails.txt', 'versions.env')


def parse_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate JSON key in gateway configuration.')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs)


def trusted(path, *, directory=False, optional=False, owner=None):
    try: info = path.lstat()
    except FileNotFoundError:
        if optional: return None
        raise
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or info.st_uid != (ROOT_UID if owner is None else owner)
            or info.st_mode & 0o022 or (not directory and info.st_nlink != 1)):
        raise ValueError(f'Untrusted type, owner, mode or link: {path}')
    return info


def trusted_parents(path, root=Path('/'), optional=False):
    for parent in reversed(path.parents):
        if parent.is_relative_to(root): trusted(parent, directory=True, optional=optional)


def check_gateway_lock(root=Path('/'), *, optional=False):
    path = root / 'etc/qacey-dev/web.lock'
    trusted_parents(path, root)
    info = trusted(path, optional=optional)
    if info is not None and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 0):
        raise ValueError('Gateway lock must be an empty root-owned regular file with mode 0600.')
    return path


@contextmanager
def gateway_lock(root=Path('/'), *, create=False):
    # Lock a private object, never the world-readable /etc directory inode.
    # Keep the inode permanently: unlinking locks would allow two owners.
    path = check_gateway_lock(root, optional=create)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    if create:
        try: descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            check_gateway_lock(root)
            descriptor = os.open(path, flags)
    else:
        descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 0):
            raise ValueError('Untrusted gateway lock descriptor.')
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError('Gateway lock changed while waiting; retry after reviewing its ownership.')
        yield descriptor
    finally: os.close(descriptor)


def hostname(value):
    if not isinstance(value, str) or len(value) > 253 or value != value.lower():
        raise ValueError('Use a lowercase public DNS hostname.')
    parts = value.split('.')
    if len(parts) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p) for p in parts):
        raise ValueError('Use a public DNS hostname without a scheme, wildcard, path or port.')
    try: ipaddress.ip_address(value)
    except ValueError: return value
    raise ValueError('Use a DNS hostname, not an IP address.')


def validate_settings(settings):
    required = {'hostname', 'issuer', 'client_id', 'emails', 'cert_resolver', 'mfa_required'}
    if not isinstance(settings, dict) or set(settings) != required:
        raise ValueError('Gateway settings must contain exactly the documented nonsecret fields.')
    hostname(settings['hostname'])
    issuer = settings['issuer']
    if not isinstance(issuer, str) or any(c.isspace() or not c.isprintable() for c in issuer):
        raise ValueError('Use an HTTPS OIDC issuer URL.')
    parsed = urlsplit(issuer)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.port not in (None, 443)
            or '\\' in issuer):
        raise ValueError('OIDC issuer must be HTTPS without userinfo, query, fragment or a non-HTTPS port.')
    hostname(parsed.hostname)
    client = settings['client_id']
    if not isinstance(client, str) or not client or len(client) > 512 or any(not c.isprintable() for c in client):
        raise ValueError('Use a nonempty printable OIDC client ID.')
    emails = settings['emails']
    if not isinstance(emails, list) or not 1 <= len(emails) <= 20:
        raise ValueError('Provide between one and twenty exact email addresses.')
    for email in emails:
        if not isinstance(email, str) or not re.fullmatch(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+', email):
            raise ValueError('Only exact email addresses are allowed; no wildcard/domain bypass.')
        hostname(email.split('@')[1].lower())
    if not isinstance(settings['cert_resolver'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', settings['cert_resolver']):
        raise ValueError('Use the name of an existing Traefik certificate resolver.')
    if settings['mfa_required'] is not True:
        raise ValueError('Configure mandatory MFA in the identity provider before preparing this gateway.')
    return dict(settings, emails=sorted(set(email.lower() for email in emails)))


def read_versions(path):
    values = dict(line.split('=', 1) for line in path.read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    result = {key: values[key] for key in ('OAUTH2_PROXY_VERSION', 'CADDY_VERSION')}
    if any(not re.fullmatch(r'v?\d+\.\d+\.\d+(?:-alpine)?', value) for value in result.values()):
        raise ValueError('Gateway images require explicit reviewed version tags.')
    return result


def render(settings, identity, versions, assets):
    settings = validate_settings(settings)
    if any(type(identity.get(k)) is not int or identity[k] <= 0 or identity[k] == 65532 for k in ('uid', 'gid')):
        raise ValueError('Use a nonroot dedicated identity distinct from the OAuth proxy identity.')
    replacements = {'@HOSTNAME@': settings['hostname'], '@CERT_RESOLVER@': settings['cert_resolver'],
                    '@ISSUER@': json.dumps(settings['issuer']), '@CLIENT_ID@': json.dumps(settings['client_id']),
                    '@UID@': str(identity['uid']), '@GID@': str(identity['gid'])}
    result = {}
    for target, source in (('compose.yml', 'compose.yml'), ('Caddyfile', 'Caddyfile.in'), ('oauth2-proxy.cfg', 'oauth2-proxy.cfg.in')):
        text = (assets / source).read_text()
        text = re.sub(r'@[A-Z_]+@', lambda match: replacements[match.group(0)], text)
        result[target] = text.encode()
    result['allowed-emails.txt'] = ('\n'.join(settings['emails']) + '\n').encode()
    result['versions.env'] = ''.join(key + '=' + versions[key] + '\n' for key in ('OAUTH2_PROXY_VERSION', 'CADDY_VERSION')).encode()
    return result


def development_record(root=Path('/')):
    records = []
    for name in ('qacey-codex', 'qacey-dev'):
        path = root / 'etc' / name / 'installation.json'
        trusted_parents(path, root); trusted(path)
        value = parse_json(path.read_text())
        if not isinstance(value, dict) or value.get('schema') != 1 or value.get('ready') is not True:
            raise ValueError('Complete Codex and native development provisioning first.')
        records.append(value)
    basis, record = records
    if any(record.get(k) != basis.get(k) for k in ('user', 'uid', 'gid', 'home')):
        raise ValueError('Development and foundation identities differ.')
    try:
        account, group = pwd.getpwnam(record['user']), grp.getgrnam(record['user'])
    except KeyError as exc: raise ValueError('The recorded development account no longer exists.') from exc
    if (account.pw_uid <= 0 or account.pw_gid <= 0 or account.pw_uid == 65532 or account.pw_gid == 65532
            or account.pw_uid != record['uid'] or account.pw_gid != record['gid']
            or group.gr_gid != record['gid'] or account.pw_dir != record['home']
            or account.pw_gecos != basis.get('marker') or set(group.gr_mem) - {record['user']}
            or set(os.getgrouplist(record['user'], record['gid'])) != {record['gid']}
            or any(p.pw_name != record['user'] and p.pw_gid == record['gid'] for p in pwd.getpwall())):
        raise ValueError('The dedicated development account, home or groups have changed.')
    home = Path(record['home'])
    info = home.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != record['uid'] or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('The development home must remain private and owned by the recorded account.')
    return record


def secret_values(path, kind, *, owner=None):
    info = trusted(path, owner=owner)
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384:
        raise ValueError('Secret file must be a small root-owned regular file with mode 0600.')
    required = ({'OAUTH2_PROXY_CLIENT_SECRET', 'OAUTH2_PROXY_COOKIE_SECRET'} if kind == 'oauth'
                else {'OPENCHAMBER_UI_PASSWORD', 'OPENCODE_PASSWORD'})
    values = {}
    try: text = path.read_text()
    except UnicodeError as exc: raise ValueError('Secret files must use UTF-8 text.') from exc
    for line in text.splitlines():
        if not line or line.startswith('#'): continue
        key, separator, value = line.partition('=')
        if not separator or key not in required or key in values or not value or any(not c.isprintable() for c in value):
            raise ValueError('Secret file has a missing/duplicate/unsupported key or invalid value.')
        if kind == 'native' and (len(value) < 24 or not re.fullmatch(r'[A-Za-z0-9_+/=.-]+', value)):
            raise ValueError('Native passwords need at least 24 unquoted base64/URL-safe characters.')
        values[key] = value
    if set(values) != required: raise ValueError('Secret file is missing required credentials.')
    if kind == 'oauth':
        if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', values['OAUTH2_PROXY_COOKIE_SECRET']):
            raise ValueError('Cookie secret must use URL-safe base64, without + or /.')
        try: cookie = base64.b64decode(values['OAUTH2_PROXY_COOKIE_SECRET'], altchars=b'-_', validate=True)
        except (ValueError, binascii.Error) as exc: raise ValueError('Cookie secret must be base64 encoded.') from exc
        if len(cookie) not in (16, 24, 32): raise ValueError('Decoded cookie secret must contain 16, 24 or 32 bytes.')
    return values


def hashes(files):
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def verify_files(directory, record, *, pending=False):
    expected = record.get('files')
    if not isinstance(expected, dict) or set(expected) != set(MANAGED):
        raise ValueError('Invalid managed gateway file record.')
    previous = record.get('previous_files', {}) if pending else {}
    for name in MANAGED:
        path = directory / name
        info = trusted(path, optional=pending)
        if info is None:
            if name in previous: raise ValueError('A previously managed gateway file is missing.')
            continue
        allowed = {expected[name], previous.get(name)}
        if hashlib.sha256(path.read_bytes()).hexdigest() not in allowed:
            raise ValueError(f'Managed gateway file changed; review it before re-provisioning: {path}')


def check_compose_version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?\s*', value)
    if not match or tuple(map(int, match.groups())) < (2, 30, 0):
        raise ValueError('Docker Compose >=2.30.0 is required for raw credential env files.')


def compose_command(directory):
    return [*DOCKER, 'compose', '--project-name', 'qacey-dev-web', '--project-directory', str(directory),
            '--env-file', str(directory / 'versions.env'), '-f', str(directory / 'compose.yml')], dict(SYSTEM_ENV)
