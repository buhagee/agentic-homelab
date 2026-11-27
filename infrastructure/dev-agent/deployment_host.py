"""Fixed host boundaries for the native updater; root never executes user runtimes."""
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

import deployment as core


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Host:
    def __init__(self, policy):
        self.policy = policy
        self.root = core.HOST_ROOT
        self.web = core.load_module('qacey_deployment_web', Path(__file__).with_name('web_config.py'))
        self.records = None
        self.native_secrets = None

    def check_records(self, *, recovery=False):
        paths = ('etc/qacey-codex/installation.json', 'etc/qacey-dev/installation.json',
                 'etc/qacey-dev/web/installation.json')
        records = [core.json_load(self.root / path) for path in paths]
        for record in records:
            if (not isinstance(record, dict) or record.get('schema') != 1
                    or type(record.get('ready')) is not bool or (not recovery and record['ready'] is not True)
                    or any(record.get(k) != self.policy[k] for k in ('user', 'uid', 'gid', 'home'))):
                raise core.Blocked('installation-records-not-ready-or-identity-changed')
        basis, native, gateway = records
        if ((native.get('port'), native.get('node')) != (self.policy['port'], self.policy['node'])
                or gateway.get('settings') != self.policy['gateway']):
            raise core.Blocked('local-selections-changed-reenrol-required')
        self.web.validate_settings(self.policy['gateway'])
        account, group = pwd.getpwnam(self.policy['user']), grp.getgrnam(self.policy['user'])
        if (account.pw_uid != self.policy['uid'] or account.pw_gid != self.policy['gid']
                or account.pw_dir != self.policy['home'] or account.pw_gecos != basis.get('marker')
                or group.gr_gid != self.policy['gid'] or set(group.gr_mem) - {account.pw_name}
                or set(os.getgrouplist(account.pw_name, account.pw_gid)) != {account.pw_gid}
                or any(p.pw_name != account.pw_name and p.pw_gid == account.pw_gid for p in pwd.getpwall())):
            raise core.Blocked('development-account-or-groups-changed')
        home = Path(account.pw_dir)
        core.parents(home)
        info = home.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise core.Blocked('development-home-changed')
        locked = core.run(['/usr/bin/passwd', '--status', account.pw_name], 'account-check').stdout.split()
        if locked[:2] != [account.pw_name, 'L']:
            raise core.Blocked('development-password-is-not-locked')
        self.web.verify_files(self.root / 'etc/qacey-dev/web', gateway,
                              pending=gateway['ready'] is not True, upgrade=True)
        self.records = records
        return records

    def credentials(self):
        paths = {'native': self.root / 'etc/qacey-dev/openchamber.env',
                 'oauth': self.root / 'etc/qacey-dev/web/oauth2.env'}
        result = {}
        for name, path in paths.items():
            core.parents(path)
            core.trusted(path, private=True)
            try:
                values = self.web.secret_values(path, name)
            except Exception:
                raise core.Blocked('missing-invalid-or-drifted-service-credentials') from None
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            if name == 'native':
                self.native_secrets = values
        return result

    def managed_paths(self):
        result = []
        for directory in ('usr/local/lib/qacey-codex', 'usr/local/lib/qacey-dev', 'usr/local/lib/qacey-dev-web'):
            base = self.root / directory
            core.parents(base)
            core.trusted(base, directory=True)
            for path in base.rglob('*'):
                if path.is_dir() and not path.is_symlink():
                    core.trusted(path, directory=True)
                else:
                    core.trusted(path)
                    result.append(path)
        result.extend(self.root / 'etc/systemd/system' / name for name in core.UNITS)
        result.extend(self.root / 'usr/local/bin' / name for name in ('qacey-codex', 'qacey-dev', 'qacey-dev-web'))
        return result

    def managed_files(self):
        values = {}
        for path in self.managed_paths():
            core.parents(path)
            core.trusted(path)
            values[str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return values

    def verify_managed(self, expected):
        if not expected or self.managed_files() != expected:
            raise core.Blocked('installed-managed-files-drifted-review-and-reenrol')

    def prepare_preview(self, source):
        """Only root-owned renderer/baseline files become readable to the user.

        The private Git source stays private. Candidate sync code is executed with
        the existing UID/GID, without supplementary groups or inherited variables.
        """
        revision = source.name
        if not core.SHA.fullmatch(revision):
            raise core.Blocked('invalid-preview-source')
        stage = self.root / core.LIBRARY / 'preview' / revision
        core.parents(stage, optional=True)
        if not stage.exists():
            stage.mkdir(mode=0o755, parents=True)
        core.trusted(stage, directory=True)
        for directory in (stage.parent, stage):
            directory.chmod(0o755)
        for name in ('sync_config.py', 'mcp_config.py', 'shared/AGENTS.md', 'shared/mcp.json'):
            destination = stage / name
            destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            core.parents(destination)
            destination.parent.chmod(0o755)
            core.atomic(destination, (source / 'infrastructure/dev-agent' / name).read_bytes(), 0o644)
        code = ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
                'import sync_config; sync_config.sync(Path(sys.argv[2]), Path(sys.argv[1]) / "shared", False)')
        core.run(['/usr/bin/python3', '-I', '-B', '-c', code, str(stage), self.policy['home']],
                 'shared-configuration-preflight', identity=self.policy)
        # Read settings as the development identity. Never read provider files as root.
        code = ('import sys; sys.path.insert(0,"/usr/local/lib/qacey-dev"); '
                'import dev_context; a,r=dev_context.current(); dev_context.check_openchamber_settings(a)')
        core.run(['/usr/bin/python3', '-I', '-B', '-c', code], 'native-settings-preflight', identity=self.policy)

    def preflight(self, source):
        web = core.load_module('qacey_candidate_gateway', source / 'infrastructure/dev-agent/web_config.py')
        files = web.render(self.policy['gateway'], self.policy, web.read_versions(source / 'versions.env'),
                           source / 'infrastructure/dev-agent/web')
        if hashlib.sha256(files[web.ORACLE_ROUTE]).hexdigest() != self.policy['verified_oracle_route']:
            raise core.Blocked('oracle-route-changed-explicit-edge-verification-and-reenrol-required')
        settings = self.root / core.STATE / 'gateway-settings.json'
        core.save(settings, self.policy['gateway'])
        arguments = (
            ('install-codex.py', ['--user', self.policy['user'], '--home', self.policy['home']]),
            ('install-dev-agent.py', ['--port', str(self.policy['port']), '--node', self.policy['node']]),
            ('install-dev-web.py', ['--settings', str(settings)]),
        )
        for name, args in arguments:
            core.run(['/usr/bin/python3', '-I', '-B', str(source / 'scripts/setup' / name), *args],
                     'provision-preflight-' + name[:-3])
        self.prepare_preview(source)
        core.run(['/usr/local/bin/qacey-dev-web', 'check'], 'gateway-preflight')

    def unit(self, name):
        properties = ('LoadState,ActiveState,SubState,UnitFileState,MainPID,ControlGroup,'
                      'ExecMainStartTimestampMonotonic,FragmentPath,User,Group,DropInPaths')
        raw = core.run(['/usr/bin/systemctl', 'show', '--no-pager', '--property=' + properties, name],
                       'unit-inspection').stdout
        values = {}
        for line in raw.splitlines():
            key, separator, value = line.partition('=')
            if not separator or key in values:
                raise core.Blocked('unexpected-systemd-inspection')
            values[key] = value
        if (values.get('LoadState') != 'loaded' or values.get('UnitFileState') in ('masked', 'masked-runtime')
                or values.get('FragmentPath') != '/etc/systemd/system/' + name or values.get('DropInPaths')):
            raise core.Blocked('unmanaged-masked-or-shadowed-native-unit')
        active = values.get('ActiveState')
        if active not in ('active', 'inactive') or values.get('SubState') not in ('running', 'listening', 'dead', 'exited'):
            raise core.Blocked('native-unit-failed-or-transitional')
        if name in (core.APP, core.TMUX, core.CODEX, core.PROXY) and (
                values.get('User') != self.policy['user'] or values.get('Group') != self.policy['user']):
            raise core.Blocked('native-service-identity-changed')
        # Sockets have no service process properties; systemctl normally omits
        # them rather than printing MainPID=0.
        pid = values.get('MainPID', '0' if name == core.SOCKET else '')
        start = values.get('ExecMainStartTimestampMonotonic', '0' if name == core.SOCKET else '')
        if not pid.isdigit() or (start and not start.isdigit()):
            raise core.Blocked('unexpected-systemd-process-identity')
        return dict(active=active == 'active', sub=values['SubState'], enabled=values.get('UnitFileState'),
                    pid=int(pid), start=start, cgroup=values.get('ControlGroup', ''))

    def docker(self, args, label='gateway-inspection'):
        return core.run([*self.web.DOCKER, *args], label).stdout

    def containers(self):
        ids = self.docker(['container', 'ls', '--all', '--filter', 'label=com.docker.compose.project=qacey-dev-web',
                           '--format', '{{.ID}}']).splitlines()
        if any(not re.fullmatch(r'[a-f0-9]{12,64}', value) for value in ids):
            raise core.Blocked('unexpected-gateway-container-id')
        result = {}
        # Inspect only selected nonsecret fields; full Docker inspect includes env secrets.
        template = ('{"id":{{json .Id}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
                    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
                    '"status":{{json .State.Status}},"running":{{json .State.Running}},'
                    '"paused":{{json .State.Paused}},"image":{{json .Config.Image}},'
                    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
                    '"networks":{{json .NetworkSettings.Networks}}}')
        for identifier in ids:
            value = json.loads(self.docker(['container', 'inspect', '--format', template, identifier]))
            service = value.get('service')
            if (value.get('project') != 'qacey-dev-web' or service not in ('oauth', 'adapter')
                    or service in result or value.get('paused') is not False
                    or value.get('status') not in ('running', 'exited', 'created')
                    or value.get('health') not in (None, 'healthy')
                    or type(value.get('running')) is not bool):
                raise core.Blocked('partial-or-unhealthy-gateway-needs-review')
            result[service] = value
        if result and (set(result) != {'oauth', 'adapter'} or len({v['running'] for v in result.values()}) != 1):
            raise core.Blocked('partial-gateway-needs-review')
        return result

    def snapshot(self, *, ingress_closed=False):
        units = {name: self.unit(name) for name in core.UNITS}
        containers = self.containers()
        gateway_active = bool(containers and containers['oauth']['running'])
        if gateway_active and (not units[core.APP]['active'] or not units[core.SOCKET]['active']):
            raise core.Blocked('active-gateway-prerequisites-inconsistent')
        if units[core.SOCKET]['active'] and not units[core.APP]['active']:
            raise core.Blocked('proxy-without-active-application')
        return dict(units=units, gateway_active=gateway_active,
                    containers={name: value['id'] for name, value in containers.items()})

    def process_identity(self, snapshot):
        app = snapshot['units'][core.APP]
        boot = (self.root / 'proc/sys/kernel/random/boot_id').read_text().strip()
        return [boot, app['active'], app['pid'], app['start'], app['cgroup']]

    def user_process_activity(self, snapshot):
        managed_tmux = snapshot['units'][core.TMUX]['pid']
        for entry in (self.root / 'proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                status = (entry / 'status').read_text()
                uid = next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1]
                if int(uid) != self.policy['uid']:
                    continue
                executable = os.readlink(entry / 'exe').removesuffix(' (deleted)')
                args = (entry / 'cmdline').read_bytes().split(b'\0')
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (OSError, ValueError, StopIteration):
                return {'state': 'unknown', 'reason': 'development-process-inspection-unavailable'}
            if Path(executable).name in ('codex', 'codex-rs') or b'_codex-run' in args:
                return {'state': 'busy', 'reason': 'codex-process-active'}
            if Path(executable).name == 'tmux' and int(entry.name) != managed_tmux:
                return {'state': 'busy', 'reason': 'additional-tmux-process-active'}
            runtime = str(Path(self.policy['home']) / '.local/share/qacey-dev/runtime') + '/'
            texts = [argument.decode('utf-8', errors='replace') for argument in args]
            opencode = executable.startswith(runtime + 'opencode-') and Path(executable).name == 'opencode'
            chamber = any(argument.startswith(runtime + 'openchamber-') and argument.endswith('/build/bin/cli.js')
                          for argument in texts)
            launching = '/usr/local/lib/qacey-dev/qacey-dev.py' in texts and 'openchamber' in texts
            if opencode or chamber or launching:
                # A supported foreground client also owns native config/runtime.
                # Exempt only the active systemd service's actual cgroup; managed
                # OpenCode uses a detached process group, so ancestry is inadequate.
                app = snapshot['units'][core.APP]
                try:
                    groups = [line.split(':', 2)[2] for line in (entry / 'cgroup').read_text().splitlines()
                              if line.startswith('0::') or ':name=systemd:' in line]
                except (FileNotFoundError, ProcessLookupError):
                    continue
                except OSError:
                    return {'state': 'unknown', 'reason': 'native-process-cgroup-unavailable'}
                if not groups:
                    return {'state': 'unknown', 'reason': 'native-process-cgroup-unavailable'}
                if (not app['active'] or not app['cgroup'] or not all(
                        group == app['cgroup'] or group.startswith(app['cgroup'] + '/') for group in groups)):
                    return {'state': 'busy', 'reason': 'foreground-native-client-active'}
        if snapshot['units'][core.TMUX]['active']:
            result = core.run(['/usr/bin/tmux', '-N', '-S', '/run/qacey-codex-tmux/server.sock',
                               'list-sessions', '-F', '#{session_id}'], 'tmux-activity',
                              identity=self.policy, check=False)
            if result.returncode:
                return {'state': 'unknown', 'reason': 'tmux-activity-unavailable'}
            if result.stdout.strip():
                return {'state': 'busy', 'reason': 'tmux-session-active'}
        return {'state': 'idle', 'reason': 'no-codex-or-tmux-work'}

    def listener_owned(self, port, role):
        if role not in ('openchamber', 'opencode') or type(port) is not int or not 1024 <= port <= 65535:
            return False
        try:
            before = self.unit(core.APP)
            if not before['active'] or before['pid'] <= 0 or not before['cgroup'].startswith('/'):
                return False
            inodes = set()
            for name, loopback in (('tcp', '0100007F'), ('tcp6', '00000000000000000000000001000000')):
                for line in (self.root / 'proc/net' / name).read_text().splitlines()[1:]:
                    fields = line.split()
                    address, raw_port = fields[1].split(':')
                    if fields[3] != '0A' or int(raw_port, 16) != port:
                        continue
                    if address != loopback or int(fields[7]) != self.policy['uid']:
                        return False
                    inodes.add(fields[9])
            if not inodes:
                return False
            found = set()
            for entry in (self.root / 'proc').iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    owned = {os.readlink(fd)[8:-1] for fd in (entry / 'fd').iterdir()
                             if os.readlink(fd).startswith('socket:[')} & inodes
                    if not owned:
                        continue
                    status = (entry / 'status').read_text()
                    uid = int(next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1])
                    groups = [line.split(':', 2)[2] for line in (entry / 'cgroup').read_text().splitlines()
                              if line.startswith('0::') or ':name=systemd:' in line]
                    if uid != self.policy['uid'] or not groups or not all(
                            g == before['cgroup'] or g.startswith(before['cgroup'] + '/') for g in groups):
                        return False
                    found.update(owned)
                except (FileNotFoundError, ProcessLookupError):
                    continue
            return found == inodes and self.unit(core.APP) == before
        except Exception:
            return False

    def probe(self, *, health_only=False, budget=30.0):
        from deployment_probe import probe
        native = self.records[1]
        if native.get('ready') is not True:
            return {'state': 'unknown', 'reason': 'native-record-incomplete'}
        self.credentials()
        return probe(port=self.policy['port'], expected_openchamber=native['openchamber_version'],
                     expected_opencode=native['opencode_version'],
                     expected_binary=str(Path(self.policy['home']) / '.local/share/qacey-dev/runtime' /
                                         ('opencode-' + native['opencode_version']) / 'opencode'),
                     ui_password=self.native_secrets['OPENCHAMBER_UI_PASSWORD'],
                     backend_password=self.native_secrets['OPENCODE_PASSWORD'],
                     validate_listener=self.listener_owned, health_only=health_only, budget=budget)

    def activity(self, snapshot, *, recovery=False):
        if snapshot['units'][core.CODEX]['active']:
            return {'state': 'busy', 'reason': 'experimental-codex-service-active'}
        activity = self.user_process_activity(snapshot)
        if activity['state'] != 'idle':
            return activity
        if snapshot['units'][core.APP]['active']:
            return self.probe()
        return {'state': 'idle', 'reason': 'application-stopped'}

    def systemctl(self, action, unit=None):
        if unit == core.TMUX or action not in ('start', 'stop', 'daemon-reload'):
            raise core.Blocked('forbidden-native-lifecycle-operation')
        core.run(['/usr/bin/systemctl', action, *([unit] if unit else [])], 'native-' + action)

    def close_ingress(self, original):
        # Revocation works without valid credentials/configuration and does not
        # need a child gateway lock held across provisioner calls.
        ids = self.docker(['container', 'ls', '--filter', 'label=com.docker.compose.project=qacey-dev-web',
                           '--format', '{{.ID}}']).splitlines()
        if any(not re.fullmatch(r'[a-f0-9]{12,64}', value) for value in ids):
            raise core.Blocked('unexpected-gateway-container-id')
        if ids:
            self.docker(['container', 'stop', '--time', '10', *ids], 'gateway-close')
        # Stop socket and forwarder explicitly; never depend on app BindsTo timing.
        for name in (core.SOCKET, core.PROXY):
            self.systemctl('stop', name)

    def stop_app(self, current):
        if current['units'][core.APP]['active']:
            self.systemctl('stop', core.APP)

    def publish(self, source):
        settings = self.root / core.STATE / 'gateway-settings.json'
        core.save(settings, self.policy['gateway'])
        for name, args in (
            ('install-codex.py', ['--user', self.policy['user'], '--home', self.policy['home']]),
            ('install-dev-agent.py', ['--port', str(self.policy['port']), '--node', self.policy['node']]),
            ('install-dev-web.py', ['--settings', str(settings)]),
        ):
            core.run(['/usr/bin/python3', '-I', '-B', str(source / 'scripts/setup' / name), *args, '--apply'],
                     'publish-' + name[:-3])
        self.check_records()

    def install_runtime_and_sync(self):
        for command, label in ((['/usr/local/bin/qacey-codex', 'install-runtime', '--apply'], 'codex-runtime'),
                               (['/usr/local/bin/qacey-dev', 'install-runtime', '--apply'], 'native-runtime'),
                               (['/usr/local/bin/qacey-dev', 'sync', '--apply'], 'shared-configuration')):
            core.run(command, label, identity=self.policy, timeout=1800)

    def reload_units(self):
        self.systemctl('daemon-reload')

    def restore_app(self, original):
        current = self.unit(core.APP)
        if original['units'][core.APP]['active'] and not current['active']:
            self.systemctl('start', core.APP)
        elif not original['units'][core.APP]['active'] and current['active']:
            raise core.Blocked('originally-stopped-application-is-active')

    def health(self, original):
        self.check_records()
        self.credentials()
        result = core.run(['/usr/local/bin/qacey-codex', 'version'], 'codex-version', identity=self.policy)
        release = core.json_load(self.root / 'usr/local/lib/qacey-codex/release.json')
        if result.stdout.strip() != 'codex-cli ' + release['version']:
            raise core.Blocked('codex-version-mismatch')
        # Verify native version and selected binary as the user, even when stopped.
        code = ('import sys; sys.path.insert(0,"/usr/local/lib/qacey-dev"); '
                'import dev_context, install_runtime; a,r=dev_context.current(); '
                's=dev_context.runtime_selection(a,r); '
                'install_runtime.verify(s["opencode"].parent,"opencode",r["opencode_version"],s["node"],a.environment(),a.home); '
                'install_runtime.verify(s["openchamber"],"openchamber",r["openchamber_version"],s["node"],a.environment(),a.home)')
        core.run(['/usr/bin/python3', '-I', '-B', '-c', code], 'native-version-and-selection', identity=self.policy)
        if original['units'][core.APP]['active']:
            # Type=simple reports active before Node and its managed backend are
            # ready. This bounded startup wait is separate from the cross-timer
            # idle gate; every attempt repeats independent listener ownership.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                result = self.probe(health_only=True, budget=min(10.0, max(0.1, deadline - time.monotonic())))
                if result['state'] == 'healthy':
                    break
                time.sleep(min(1.0, max(0, deadline - time.monotonic())))
            else:
                raise core.Blocked('application-health-not-ready-fix-forward-required')

    def protected_socket(self):
        path = self.root / 'run/qacey-dev-proxy/backend.sock'
        core.parents(path)
        info = path.lstat()
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.policy['uid']
                or info.st_gid != self.policy['gid'] or stat.S_IMODE(info.st_mode) != 0o600):
            raise core.Blocked('unprotected-native-proxy-socket')

    def restore_ingress(self, original):
        for name in (core.SOCKET, core.PROXY):
            if original['units'][name]['active']:
                self.systemctl('start', name)
        if original['units'][core.SOCKET]['active']:
            self.protected_socket()
        if original['gateway_active']:
            core.run(['/usr/local/bin/qacey-dev-web', 'start', '--verified-oracle-route',
                      self.policy['verified_oracle_route']], 'gateway-restore', timeout=180)

    def gateway_readiness(self, containers):
        versions = self.web.read_versions(self.root / 'etc/qacey-dev/web/versions.env')
        images = {'oauth': 'quay.io/oauth2-proxy/oauth2-proxy:' + versions['OAUTH2_PROXY_VERSION'],
                  'adapter': 'caddy:' + versions['CADDY_VERSION']}
        opener = build_opener(ProxyHandler({}), NoRedirect())
        for name, value in containers.items():
            if not value['running'] or value['image'] != images[name]:
                raise core.Blocked('gateway-image-or-running-state-mismatch')
            addresses = [network.get('IPAddress') for network in value['networks'].values() if network.get('IPAddress')]
            if not addresses or any(not ipaddress.ip_address(address).is_private for address in addresses):
                raise core.Blocked('gateway-network-inspection-failed')
            # The adapter's wrong-host check proves readiness without opening a
            # backend socket or activating an originally dormant proxy service.
            port, path, expected = (4180, '/ping', 200) if name == 'oauth' else (8080, '/health', 421)
            request = Request('http://' + addresses[0] + ':' + str(port) + path,
                              headers={'Host': 'qacey-deploy-readiness.invalid'})
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    with opener.open(request, timeout=min(3, max(0.1, deadline - time.monotonic()))) as response:
                        actual = response.status
                except HTTPError as response:
                    actual = response.code
                    response.close()
                except Exception:
                    actual = None
                if actual == expected:
                    break
                time.sleep(min(1.0, max(0, deadline - time.monotonic())))
            else:
                raise core.Blocked('gateway-not-ready-fix-forward-required')

    def verify_restored(self, original):
        current = self.snapshot()
        for name in core.UNITS:
            before, after = original['units'][name], current['units'][name]
            if before['enabled'] != after['enabled']:
                raise core.Blocked('native-unit-enablement-changed')
            # Socket activation may naturally start its forwarder after ingress
            # reopens. The updater itself starts only a previously active proxy.
            dormant_proxy = name == core.PROXY and not before['active'] and original['units'][core.SOCKET]['active']
            if before['active'] != after['active'] and not dormant_proxy:
                raise core.Blocked('native-unit-active-state-mismatch')
        if current['gateway_active'] != original['gateway_active']:
            raise core.Blocked('gateway-active-state-mismatch')
        if original['units'][core.SOCKET]['active']:
            self.protected_socket()
        if original['gateway_active']:
            self.gateway_readiness(self.containers())
