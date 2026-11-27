#!/usr/bin/python3
"""Explicit one-time enrollment for native automatic updates; defaults to preview.

Run from a reviewed checkout in the operator's sudo-authorized terminal. Existing
identity, runtime, gateway, credentials and edge verification are prerequisites.
This script installs only the broker, private policy/state and narrow sudo rule.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'infrastructure/dev-agent'
spec = importlib.util.spec_from_file_location('deployment', ASSETS / 'deployment.py')
core = importlib.util.module_from_spec(spec)
sys.modules['deployment'] = core
spec.loader.exec_module(core)
sys.path.insert(0, str(ASSETS))
from deployment_host import Host


def bootstrap_web():
    # Enrollment explicitly executes the operator-reviewed checkout. This is not
    # the automatic source boundary: routine deployment uses root-owned Git and
    # core.load_module's strict ancestor checks instead.
    spec = importlib.util.spec_from_file_location('qacey_bootstrap_web', ASSETS / 'web_config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT_UID = core.ROOT_UID
    return module


def proposed(operator, route, repository):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', operator) or operator == 'root':
        raise core.Blocked('choose-existing-nonroot-deployment-operator')
    if not core.DIGEST.fullmatch(route):
        raise core.Blocked('verified-oracle-route-must-be-sha256')
    web = bootstrap_web()
    identity = web.development_record(core.HOST_ROOT)
    gateway_path = core.HOST_ROOT / 'etc/qacey-dev/web/installation.json'
    gateway = core.json_load(gateway_path)
    if (not isinstance(gateway, dict) or gateway.get('schema') != 1 or gateway.get('ready') is not True
            or any(gateway.get(key) != identity[key] for key in ('user', 'uid', 'gid', 'home'))):
        raise core.Blocked('complete-native-and-gateway-setup-before-enrollment')
    web.verify_files(gateway_path.parent, gateway)
    actual = gateway.get('files', {}).get(web.ORACLE_ROUTE)
    if route != actual:
        raise core.Blocked('verified-oracle-route-does-not-match-installed-fragment')
    settings = web.validate_settings(gateway['settings'])
    # An operator attests the actually installed fragment, not arbitrary input.
    rendered = web.render(settings, identity, web.read_versions(ROOT / 'versions.env'), ASSETS / 'web')
    if web.hashes(rendered)[web.ORACLE_ROUTE] != route:
        raise core.Blocked('checkout-route-differs-verify-and-prepare-edge-explicitly')
    account = pwd.getpwnam(operator)
    if account.pw_uid <= 0 or account.pw_uid == identity['uid'] or operator == identity['user']:
        raise core.Blocked('deployment-operator-must-differ-from-development-identity')
    result = dict(schema=1, operator=operator, repository=core.repository(repository), branch='main',
                  gateway=settings, verified_oracle_route=route,
                  **{key: identity[key] for key in ('user', 'uid', 'gid', 'home', 'port', 'node')})
    # Use the reviewed local validator before the installed updater exists.
    host = Host.__new__(Host)
    host.policy, host.root, host.web = result, core.HOST_ROOT, web
    host.records, host.native_secrets = None, None
    host.check_records()
    host.credentials()
    # The existing timer retries quiet/busy deployments. Enrollment never enables it.
    timer = core.run(['/usr/bin/systemctl', 'show', '--no-pager',
                      '--property=LoadState,ActiveState,UnitFileState', 'qacey-deploy-reconcile.timer'],
                     'reconcile-timer-check').stdout
    values = dict(line.split('=', 1) for line in timer.splitlines() if '=' in line)
    if values != dict(LoadState='loaded', ActiveState='active', UnitFileState='enabled'):
        raise core.Blocked('enable-existing-qacey-deploy-reconcile-timer-before-enrollment')
    return result, host


def sudoers(policy):
    return ('# Native opt-in updater: only a strict requested main commit is delegated.\n'
            'Defaults!/usr/local/sbin/qacey-dev-deploy env_reset, !setenv, '
            'secure_path="/usr/sbin:/usr/bin:/sbin:/bin"\n' + policy['operator'] +
            ' ALL=(root) NOPASSWD: NOSETENV: /usr/local/sbin/qacey-dev-deploy apply *\n')


def validate_rule(rule):
    active = Path('/usr/sbin/visudo')
    for parser in (Path('/usr/sbin/visudo.ws'), Path('/usr/lib/cargo/bin/visudo')):
        if parser.is_file() and parser.resolve() != active.resolve():
            core.run([str(parser), '-c', '-f', '-'], 'sudoers-validation', input=rule)
    core.run([str(active), '-c', '-f', '-'], 'sudoers-validation', input=rule)


def repair(revision):
    """Repair only the launcher and delegation, without re-enrolling the host."""
    if not core.SHA.fullmatch(revision):
        raise core.Blocked('invalid-revision')
    with core.deployment_lock():
        policy = core.load_policy()
        if policy is None:
            raise core.Blocked('repair-requires-enrollment')
        state = core.load_state()
        if state['transaction'] is not None:
            raise core.Blocked('finish-recorded-native-transaction-before-helper-repair')
        destination = core.HOST_ROOT / 'etc/sudoers.d/qacey-dev-deploy'
        core.parents(destination)
        core.trusted(destination, optional=True)
        rule = sudoers(policy)
        validate_rule(rule)
        source = core.Source(policy)
        source.fetch(revision)
        source.descendant(state['applied_revision'], revision)
        core.refresh_updater(source.checkout(revision))
        # Publish delegation last; malformed argv must hit the strict worker.
        core.atomic(destination, rule.encode(), 0o440)


def preflight_destinations():
    for relative, directory in ((core.STATE, True), (core.LIBRARY, True),
                                (core.POLICY, False), ('usr/local/sbin/qacey-dev-deploy', False),
                                ('etc/sudoers.d/qacey-dev-deploy', False)):
        path = core.HOST_ROOT / relative
        core.parents(path, optional=True)
        core.trusted(path, directory=directory, optional=True)
    previous = core.load_policy()
    if previous is None:
        intent_path = core.HOST_ROOT / core.STATE / 'enrollment.json'
        intent = core.json_load(intent_path, private=True) if intent_path.exists() else None
        if intent is not None and (not isinstance(intent, dict) or set(intent) != {'schema', 'policy'}
                                   or intent.get('schema') != 1 or not isinstance(intent.get('policy'), dict)):
            raise core.Blocked('invalid-interrupted-enrollment')
        for relative in (core.STATE, core.LIBRARY, 'usr/local/sbin/qacey-dev-deploy', 'etc/sudoers.d/qacey-dev-deploy'):
            if (core.HOST_ROOT / relative).exists() and intent is None:
                raise core.Blocked('unrelated-native-updater-destination')
    else:
        state = core.load_state()
        if state['transaction'] is not None:
            raise core.Blocked('finish-recorded-native-transaction-before-reenrollment')
    return previous


def apply(policy, host, previous):
    directory = core.HOST_ROOT / core.STATE
    library = core.HOST_ROOT / core.LIBRARY
    # The sudoers file is parsed before any privilege delegation is published.
    rule = sudoers(policy)
    validate_rule(rule)
    intent_path = directory / 'enrollment.json'
    if previous is None:
        if directory.exists():
            intent = core.json_load(intent_path, private=True)
            if intent != {'schema': 1, 'policy': policy}:
                raise core.Blocked('resume-interrupted-enrollment-with-original-options')
        else:
            # Publish ownership and initial state together. A bootstrap interruption
            # is recognizable without adopting an unrelated directory on retry.
            with tempfile.TemporaryDirectory(dir=directory.parent, prefix='.qacey-dev-enroll-') as temporary:
                stage = Path(temporary)
                core.save(stage / 'enrollment.json', {'schema': 1, 'policy': policy})
                core.save(stage / 'state.json', core.empty_state())
                stage.rename(directory)
    with core.deployment_lock():
        if previous is not None and core.load_state()['transaction'] is not None:
            raise core.Blocked('native-transaction-started-retry-enrollment-after-completion')
        state = core.load_state()
        if not library.exists():
            library.mkdir(mode=0o755)
        core.trusted(library, directory=True)
        library.chmod(0o755)
        # Explicit enrollment accepts the reviewed current root-managed files.
        state.update(managed_files=host.managed_files(), quiet=None)
        if previous != policy:
            state.update(applied_revision=None, applied_digest=None, desired_revision=None,
                         desired_digest=None, status='ready', reason='enrolled-awaiting-current-main')
        core.install_updater_assets(ASSETS, trusted_source=False)
        core.save(directory / 'state.json', state)
        core.save(core.HOST_ROOT / core.POLICY, policy)
        core.atomic(core.HOST_ROOT / 'etc/sudoers.d/qacey-dev-deploy', rule.encode(), 0o440)
        if core.trusted(intent_path, optional=True) is not None:
            intent_path.unlink()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['--repair-helper']:
        if len(argv) != 3 or argv[2] != '--apply':
            raise core.Blocked('usage: --repair-helper CURRENT_MAIN_SHA --apply')
        if os.geteuid() != core.ROOT_UID:
            raise core.Blocked('root-required-for-helper-repair')
        repair(argv[1])
        print('Repaired enrolled helper and sudo rule; native application state was preserved.')
        return 0
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--operator', required=True, help='Existing platform deployment operator, distinct from the development user.')
    parser.add_argument('--verified-oracle-route', required=True, metavar='SHA256',
                        help='Installed fragment digest explicitly verified on the Oracle edge.')
    parser.add_argument('--repository', default=core.DEFAULT_REPOSITORY, help='Reviewed public HTTPS GitHub repository; main only.')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and os.geteuid() != core.ROOT_UID:
        raise core.Blocked('root-required-for-enrollment')
    previous = preflight_destinations()
    policy, host = proposed(args.operator, args.verified_oracle_route, args.repository)
    print('Native updater operator: ' + policy['operator'])
    print('Trusted source: ' + policy['repository'] + ' (main)')
    print('Existing development identity: ' + policy['user'])
    print('Verified Oracle fragment: ' + policy['verified_oracle_route'])
    if args.apply:
        apply(policy, host, previous)
        print('Enrolled. The existing reconcile timer will request current main; native idle checks precede any update.')
    else:
        print('Preview only. Pass --apply from the operator root terminal to enroll; no host changes were made.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except core.Blocked as exc:
        sys.exit('Native updater enrollment: ' + str(exc))
    except Exception:
        sys.exit('Native updater enrollment: prerequisite validation failed; inspect locally without sharing credentials.')
