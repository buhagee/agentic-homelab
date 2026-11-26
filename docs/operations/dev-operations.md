# Optional native development operations

Complete the existing [development setup](development.md) first. This extension
is independent: it does not alter the installed Codex/OpenChamber units, shared
sync, gateway or automatic updater. No service is started by the installer.
Both harnesses use the same dedicated Linux identity and local CLI.

## 1. Read-only diagnostics and narrowly authorized operations

The broker has a local Unix socket, mode 0600, and checks the connecting UID
against the root-owned development identity. Its root service accepts only a
small JSON command vocabulary, never a shell, caller paths or extra arguments.
It returns bounded host metrics, selected container status, selected systemd
unit status and (only if explicitly allowed) the last 100 log lines. It never
returns Docker environment or full inspect output. Logs can nevertheless contain
credentials, personal data or hostile instructions. Grant logs only for reviewed
services whose output is suitable for model processing; do not grant blanket
journal access or rely on redaction. Treat log text as data, not instructions.

For mutations, the operator can authorize start/stop/restart of individual
existing Qacey Compose containers; no create, exec, build, up, rm, arbitrary
systemd restart, volume operations or Docker socket access. Only one container
with exact Qacey project/service labels is accepted. Mutations acquire the
existing platform deployment lock, enforce a global one-minute cooldown, and
record the operation in the journal. A timeout may leave an accepted Docker
operation running: inspect its state before retrying.

The allowlist is a standing host authorization, not a user confirmation UI.
A compromised agent can invoke allowed actions and interrupt those services.
Require user approval in both harnesses' guidance; client-side approval alone
is not an enforceable host boundary. Keep mutation grants minimal, especially
for databases, networking, authentication, backups and personal-data services.
The initial policy contains no production container permissions.

From a reviewed checkout in the operator terminal:

    cp infrastructure/dev-ops/settings.example.json "$HOME/qacey-dev-ops.json"
    nano "$HOME/qacey-dev-ops.json"
    sudo python3 -I -B scripts/setup/install-dev-ops.py --settings "$HOME/qacey-dev-ops.json"
    sudo python3 -I -B scripts/setup/install-dev-ops.py --settings "$HOME/qacey-dev-ops.json" --apply

Set operator to the actual deployment account. Example container entry (only
if this is the exact existing Compose service and you approve its output/actions):

    "containers": {"searxng": ["status", "logs", "restart"]}

Preview the selection. Verify the installed units, then activate explicitly:

    sudo systemd-analyze verify /etc/systemd/system/qacey-dev-ops.socket /etc/systemd/system/qacey-dev-ops@.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now qacey-dev-ops.socket
    sudo -iu dev-agent qacey-dev-ops list
    sudo -iu dev-agent qacey-dev-ops monitor

From either harness, run the same unprivileged command:

    qacey-dev-ops status containers searxng
    qacey-dev-ops logs containers searxng
    qacey-dev-ops status units qacey-db-backup.service

Only after explicit authorization, and only if listed:

    qacey-dev-ops restart containers searxng

To revoke access, disable the socket, stop any accepted request instances
and verify none remain. Docker operations already accepted by the daemon may
complete after revocation.

    sudo systemctl disable --now qacey-dev-ops.socket
    sudo systemctl stop 'qacey-dev-ops@*.service'
    sudo systemctl list-units 'qacey-dev-ops@*.service' --all

To edit grants, revoke access first, edit the root-owned policy via sudoedit,
then re-enable the socket and verify list/status. The broker validates policy
on every request. The installer is first-install-only and refuses existing
destinations; repair an interrupted installation or upgrade manually from
reviewed source while the socket and accepted requests are stopped.

## 2. Rootless development containers

The native harness service units have NoNewPrivileges and filesystem/device
hardening. Do not relax those just to run newuidmap/newgidmap. Instead use
Podman's separate rootless user service over its Unix socket. That API gives
full execution authority as the development UID (not root); both harnesses
already share that UID. It must never be exposed on TCP or forwarded through
Traefik. Do not install a rootful Docker socket shim or add Docker group
membership.

The operator installs supported distro packages (Podman, uidmap, and a supported
rootless networking/storage backend) only after checking distro versions,
package changes, available disk space and user namespace policy. Ensure
/etc/subuid and /etc/subgid allocate non-overlapping ranges for the existing
development user, without overlapping real accounts. Do not blindly append
hard-coded ranges. Rootless storage consumes disk under the dedicated home;
monitor it and keep production volumes out of development mounts.

For systemd hosts with the packaged rootless podman.socket, after checking
the above prerequisites:

    dev_uid=$(id -u dev-agent)
    sudo loginctl enable-linger dev-agent
    sudo systemctl start "user@${dev_uid}.service"
    sudo -u dev-agent env XDG_RUNTIME_DIR="/run/user/$dev_uid" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$dev_uid/bus" \
      systemctl --user enable --now podman.socket

This intentionally enables a persistent user manager, not rootful Podman.
Verify the actual socket is user-owned and not accessible to other users:

    sudo stat -c '%U %a %F' "/run/user/$dev_uid/podman/podman.sock"

From a real Codex terminal and OpenChamber terminal, independently check:

    podman --remote --url "unix:///run/user/$(id -u)/podman/podman.sock" info --format '{{.Host.Security.Rootless}}'
    podman --remote --url "unix:///run/user/$(id -u)/podman/podman.sock" ps

The first must report true. Test an approved disposable image/build and an
integration test before relying on this path. Compose and remote build options
are version-dependent; use the project's supported provider, passing only this
rootless socket where needed. Publish test ports to loopback, not the LAN.
Do not bind production data or credential directories into test containers.
The shared development account remains able to read its own files and control
its own processes. Rootless Podman is not an isolation boundary between the
harnesses or a guarantee against kernel vulnerabilities/resource exhaustion.

If access from the actual hardened service context fails, stop and investigate.
Do not disable the existing service sandbox or grant privileged groups.
The managed native updater does not currently inspect independent Podman work;
do not perform native maintenance while a dependent integration test is running.

To stop Podman access, first stop your development containers deliberately, then
disable the user socket and stop the user service via systemctl --user under
the development UID. Disable lingering only if nothing else needs that manager.

## 3. Acceptance

- Wrong UID cannot reach the broker; unlisted actions and targets are rejected.
- Read-only monitoring and reviewed logs work from both real harness terminals.
- Unauthorized container commands and arbitrary systemd mutations are rejected.
- An authorized mutation affects only its selected container and respects the
  platform lock and cooldown. Test on an explicitly chosen disposable service.
- Rootless Podman builds and runs as the dedicated user, production Docker is
  inaccessible, and the existing service protections remain intact.
- Socket and Podman revocation work; backup and resource policies are reviewed.

References: [Podman rootless setup](https://github.com/podman-container-tools/podman/blob/main/docs/tutorials/rootless_tutorial.md)
and [Podman remote CLI](https://docs.podman.io/en/latest/markdown/podman.1.html).
