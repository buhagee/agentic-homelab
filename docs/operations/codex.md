# Codex on the home server

This is an opt-in native development environment. It adds a dedicated account,
private state, a pinned runtime installer and a disabled remote-access unit. It
does not replace the running OpenCode/Hermes stack or install itself through the
platform deployment pipeline.

The implementation and its boundaries are described in the
[foundation design](../designs/2026-11-26-codex-foundation.md).

## Recommended phone access

Use the [shared Codex/OpenChamber HTTPS runbook](development.md) for the headless
server. It reuses this foundation account and Codex login, adds OpenCode chat and
a web terminal, and gives Codex sessions an independent tmux lifetime. Steps 1–4
below remain the foundation onboarding. The remote-control pairing in step 5 is
an optional experimental alternative and is not required by the HTTPS setup.

## Existing projects may be live

The owner keeps projects under their `~/projects`. The deployment sources support
that possibility: `scripts/deploy/auto-deploy.sh` defaults to
`$HOME/projects/qacey-platform`, while the root dispatcher embeds the checkout
from which its installer ran. The reconciliation unit also contains an installed
checkout path. Some older instructions use `/srv/agentic-homelab` instead.

The private `buhagee/homeserver-deploy` repository is a dispatcher, not a project
directory inventory. Its workflow invokes the host's allowlisted command; it does
not resolve all active application paths. Inspect the installed dispatcher,
reconciliation unit and application bind mounts on the host before treating an
existing checkout as disposable or writable development space.

Codex starts with **fresh clones in its own account's `~/projects`**. Existing
operator checkouts, their ownership, their Git metadata and running bind mounts
are left alone. Do not create a linked worktree from a live deployment checkout:
that still shares its common Git directory. Worktrees from the independent
development clone are suitable for parallel tasks.

## 1. Review and provision the account

Requirements: Linux with systemd, Python 3.11+, Git and normal account-management
tools. Runtime installation needs outbound HTTPS to the official installer and
its release hosts. No Node/npm installation is required for this route.

Every ancestor of the new home must already be a real, root-owned directory.
Provisioning checks Unix mode bits before creating the account. Each ancestor
must grant search permission to group and others and deny both write permission
(for example, mode `0711` or `0755`). Use directories without ACLs that
restrict traversal by the dedicated user. The installer creates the home below
these directories.

From the reviewed repository checkout, inspect the default plan:

```sh
python3 scripts/setup/install-codex.py
```

The defaults are account `dev-agent` and home `/home/dev-agent`. For an alternate
home on the local SSD, first confirm that the intended disk is mounted at
`/mnt/ssd`. If the mount is missing or the source is wrong, stop here.

```sh
findmnt --mountpoint /mnt/ssd
```

Choose a sibling of `/mnt/ssd/qacey`. The platform's `server-setup-home.sh`
recursively changes ownership of that subtree to the operator.

```sh
python3 scripts/setup/install-codex.py --user dev-agent --home /mnt/ssd/dev-agent
```

After reviewing the output, run the **same arguments** with `sudo` and `--apply`.
For the default location, run `sudo python3 scripts/setup/install-codex.py --apply`.
For the SSD example, also pass `--user dev-agent --home /mnt/ssd/dev-agent`.
First installation rejects unrelated accounts, homes and system destinations.
This includes same-named units, unit-specific drop-ins and enablement links in
standard systemd unit directories. Reruns recognize their own installation,
verify the private primary group and preserve user-edited config, guidance and
authentication.

Provisioning does not download or execute Codex, authenticate, pair a device,
start a daemon, enable a unit, change existing project ACLs or grant sudo/Docker
membership. It prints the remaining manual steps.

### Installed layout

| Location | Ownership and purpose |
| --- | --- |
| `/etc/qacey-codex/installation.json` | Root-owned non-secret account/path record. |
| `/usr/local/lib/qacey-codex/` | Root-owned runtime/launcher helpers and release pin. |
| `/usr/local/bin/qacey-codex` | Common launcher for interactive and service use. |
| `/etc/systemd/system/qacey-codex.service` | Disabled system unit running as the dedicated account. |
| Dedicated home `projects/` | Independent development clones and their worktrees. |
| Dedicated home `.codex/` | User-owned config, authentication and runtime/session state. |
| Dedicated home `.local/bin/` | User runtime entry points. |

## 2. Install the pinned runtime as the dedicated user

Enter the account from your own sudo-authorized administrative session:

```sh
sudo -iu dev-agent
qacey-codex install-runtime
qacey-codex install-runtime --apply
qacey-codex version
```

The first runtime command is a dry-run. The second verifies the reviewed official
installer's SHA-256 before running it as the non-root account, requests stable
Codex `0.172.0`, and disables the installer's automatic launch prompt. The full
package retains the helpers needed by the managed daemon. A wrong-user or root
runtime invocation is rejected.

If the upstream installer changes, checksum verification deliberately stops.
Review and update `infrastructure/codex/release.json`; do not bypass the check or
replace the pin with an unreviewed download. Verify both the installer contents
and the requested stable release when updating.

## 3. Sign in and create a development clone

Still as `dev-agent`:

```sh
qacey-codex login
qacey-codex login-status
git clone https://github.com/buhagee/agentic-homelab.git \
  "$HOME/projects/agentic-homelab"
qacey-codex run "$HOME/projects/agentic-homelab"
```

The device-login command prints the supported verification flow. Complete it
yourself; enable device-code login in ChatGPT security settings if required by
the account. ChatGPT sign-in uses subscription access. API-key authentication
uses a different billing route and is not part of this setup.

Authenticate GitHub separately under this account if private clones or pushes are
needed. Grant only the repository access intended for development. Do not copy
the operator's whole SSH directory, credential store or platform environment.
Development secrets, if necessary for a project, should be supplied deliberately
for that project.

`run PROJECT` requires an explicit Git working tree under the dedicated development
root. It resolves symlinks and checks the common Git directory, so a linked worktree
pointing back into the operator's live repository is rejected. Paths containing
spaces are supported. The launcher has no arbitrary flag-forwarding path that
silently changes the checked working directory.

The same account/state is used by login, the runtime, the service and pairing.
Remote clients can choose their own project path; they should also choose these
development clones. Launcher validation is not claimed to intercept every remote
client operation; Linux account permissions remain the underlying boundary.

## Development permissions and privileged work

The seeded config allows ordinary project changes across the dedicated `projects`
root and enables development networking for package downloads and API access.
Approval is on request with a human reviewer. The model is selected through the
account/client rather than pinned to an entitlement that might not exist.

The account receives no sudoers entry, supplementary administrative group or
production Docker socket. The normal rootful Docker group is itself root-level
access; do not add it as a shortcut to running builds. Consider a separate rootless
development-container setup only if a project requires it.

For an occasional privileged operation:

1. Have Codex prepare the exact command or small reviewed change.
2. Run it in your own sudo-authorized SSH terminal and enter the password there.
3. Return the non-sensitive result and let Codex continue verification.

A Codex approval is not a sudo password prompt. Do not send the password in chat,
through a tool's stdin, or in an environment variable. Do not launch the agent as
root. Authenticating sudo in another terminal is not a reliable way to unlock a
detached process; timestamp scope can differ. The dedicated account cannot borrow
the operator's sudo permissions merely by receiving their password.

## 4. Add the selected workflow capabilities

Keep Superpowers as the implementation workflow and Gstack as explicitly invoked
planning/review lenses. The existing [tooling policy](agent-tooling.md) lists the
approved Gstack subset. This installer does not install workflow plugins, browsers,
third-party CLIs, personal MCP adapters or an additional orchestrator.

For Superpowers, open `/plugins` in the dedicated Codex session, select the official
Superpowers plugin and install it once. In the dedicated account's shell, inspect
the installed plugins with the selected CLI:

```sh
CODEX_HOME="$HOME/.codex" "$HOME/.local/bin/codex" plugin list --json
```

Record the installed version and start a fresh session as directed by the client.
The catalog installs its offered version; this is not a promise of the reviewed
Superpowers `v7.0.2`. The existing OpenCode pin does not install the plugin into
Codex. Do not add a second manual copy beside a plugin-owned installation.

Gstack's current Codex host is experimental. Its native `--host codex` rendering
must be curated separately from the existing OpenCode install; do not run
`setup-gstack-lenses.sh` expecting it to configure Codex. Preserve the approved
lenses and disabled outside reviews. Gstack can continue to support design in the
planning interface while the initial Codex pilot uses Superpowers and the durable
repository task brief.

Before enabling native Gstack, review the supported host setup, disable unwanted
skills, and verify the **actual discovered skill names** in Codex. Keep the pinned
source checkout outside discovered skill directories. Configure Gstack's disabled
skill complement, telemetry/update preferences and `codex_reviews disabled`
before running its setup. The approved lens list is the same as for OpenCode.

Native Codex `[[skills.config]]` entries can disable skills by exact name. At the
reviewed Gstack `v1.99.5.0`, explicitly exclude `gstack`, `gstack-upgrade` and the
non-approved `plan-design-review` runtime copy before setup. Gstack's own disabled
skill setting rejects the first two names. Removing only a top-level symlink
does not handle nested runtime copies. Generated directories such as
`gstack-review` can still contain `name: review`, so inspect frontmatter and the
active `/skills` catalog, not just directory names.

Gstack's `--no-browser` skips browser bootstrap; it is not a tool-permission
boundary. Its Codex safety hooks are advisory. The initial pilot deliberately
leaves this optional curation as a reviewed onboarding task rather than silently
installing the entire catalog.

## 5. Optional experimental remote-control pairing

After sign-in and a successful local task, return to the administrative account:

```sh
exit
sudo systemctl daemon-reload
sudo systemctl enable --now qacey-codex.service
sudo -iu dev-agent qacey-codex status
sudo -iu dev-agent qacey-codex pair
```

Complete pairing on the actual phone/account. Direct Linux pairing is experimental;
host acceptance must establish that the client can reach the intended project,
show approvals, reconnect and recover after a reboot. If the account/client does
not expose this path, use the documented desktop/SSH bridge or an SSH terminal
while keeping the existing interface available.

The unit invokes managed `remote-control start/stop`. Do not substitute
`remote-control --no-daemon`: the pinned version's foreground server uses a
different socket from the ordinary pairing command.

### Health and stopping

```sh
sudo -iu dev-agent qacey-codex status
sudo systemctl status qacey-codex.service
sudo journalctl -u qacey-codex.service --since today
```

The unit is `Type=oneshot` with `RemainAfterExit=yes`. Its active state records a
successful start action, not continuous health supervision of the detached daemon.
`qacey-codex status` performs a passive daemon-version probe; it must not start a
daemon. Investigate an unsuccessful probe even when systemd says active. This
foundation does not claim automatic crash recovery. The unit allows 900 seconds
to stop. The pinned daemon may wait 375 seconds for its lifecycle lock, up to
300 seconds for graceful shutdown, and another 10 seconds each for PID
initialization and forced exit.

### Disable remote access or roll back the pilot

Finish active work first. Stopping the systemd unit preserves the saved
remote-control preference. A later local CLI session can start the daemon again,
so also turn off remote control in the dedicated account's state.

```sh
sudo systemctl disable --now qacey-codex.service
sudo -iu dev-agent
qacey-codex stop
```

The explicit stop also covers a managed daemon started outside the unit and
succeeds if it is already stopped. Resolve any stop error before disabling
remote control, since changing the preference restarts a running daemon. Still
in the dedicated account's shell:

```sh
export CODEX_HOME="$HOME/.codex"
"$HOME/.local/bin/codex" app-server daemon disable-remote-control
qacey-codex status
exit
```

Check that the disable command succeeds and reports `"remoteControlEnabled":false`.
The passive status probe should report the daemon unavailable and exit nonzero.
Review paired devices and revoke access separately in the account's connection
controls as needed. Retain the dedicated home and its work until the operator
has reviewed what is unique.

## Update an initialized installation

Record the current CLI, daemon and workflow-plugin versions. Review the desired
release and installer SHA-256 in `infrastructure/codex/release.json`. The
interactive CLI and managed daemon have separate package selections. In the
administrative shell, check the unit's current state and record whether it
should return to service after the update:

```sh
systemctl show qacey-codex.service --property=ActiveState,UnitFileState
restore_active=no
```

Set `restore_active=yes` in that shell only for a previously active pilot you
intend to restart. Keep `restore_active=no` for an intentionally stopped or
disabled pilot. Finish remote work and stop the daemon before updating it,
since the update restarts a running daemon.

```sh
sudo systemctl stop qacey-codex.service
sudo -iu dev-agent qacey-codex stop
```

Once both stops succeed, rerun provisioning from the reviewed checkout to
refresh the root-owned copy of `release.json` and the helpers. Use the original
`--user` and `--home` arguments for a non-default installation. With the default
account and home:

```sh
sudo python3 scripts/setup/install-codex.py --apply
sudo systemctl daemon-reload
sudo -iu dev-agent
qacey-codex install-runtime
qacey-codex install-runtime --apply
qacey-codex version
```

Confirm the CLI version matches the reviewed pin. Still as the dedicated
account, update the initialized daemon from that exact CLI package:

```sh
export CODEX_HOME="$HOME/.codex"
"$HOME/.local/bin/codex" app-server daemon update --from-cli
exit
```

`--from-cli` copies and pins the full invoking package. A bare daemon update
selects the latest stable release. For a first install, follow the sign-in and
activation steps above. After a successful update, return to the same
administrative shell. Restore remote access only when previously selected:

```sh
if [ "${restore_active:-no}" = yes ]; then
  sudo -iu dev-agent qacey-codex login-status &&
    sudo systemctl start qacey-codex.service &&
    sudo -iu dev-agent qacey-codex status
fi
```

For a restored service, compare its `appServerVersion` with the reviewed pin
and CLI version before resuming remote work. For a stopped or disabled pilot,
the update ends with the daemon stopped and its saved remote-control preference
preserved.

## Backup and retirement

- Back up uncommitted development work and useful state intentionally. Authentication
  files are credentials: include them only in encrypted backup handling. Existing
  platform backup scripts do not automatically cover this new account. Reproducible
  package caches need not consume the existing backup budget.
- Do not remove Hermes or its data during this pilot. The later cleanup must preserve
  OpenCode's current state below `/mnt/ssd/qacey/hermes/opencode-v2` before deleting
  the old parent directory.

## Verification checklist

Repository validation is offline: temporary directories, fake external processes,
configuration parsing and focused permission/path tests. Run:

```sh
bash scripts/testing/run-all.sh
```

Host acceptance after the operator installs and activates:

- [ ] Expected runtime version and no additional administrative groups.
- [ ] Independent clone, ordinary edit/build/test, and reviewable branch or PR.
- [ ] Existing operator checkouts and production permissions unchanged.
- [ ] Sign-in and subsequent commands use the same dedicated state directory.
- [ ] Actual daemon probe, phone pairing, approval display and reconnect work.
- [ ] Reboot/startup and a manual sudo handoff work as intended.
- [ ] Needed development state has explicit backup coverage.

**Merge consequence:** this repository dispatches deployment on pushes to `main`,
and the reconciliation timer can also deploy it. Merging this PR does not install
or activate Codex, but it may run the pre-existing platform deployment pipeline.
Review and schedule the merge accordingly.

## References

- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Remote connections](https://learn.chatgpt.com/docs/remote-connections)
- [CLI developer commands](https://learn.chatgpt.com/docs/developer-commands)
- [Managed daemon commands and package updates in 0.172.0](https://github.com/openai/codex/blob/rust-v0.172.0/codex-rs/app-server-daemon/README.md)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Superpowers installation](https://github.com/obra/superpowers/tree/v7.0.2#codex-cli)
- [Gstack host guidance](https://github.com/garrytan/gstack/blob/v1.99.5.0/docs/hosts.md)
- [Docker privilege boundary](https://docs.docker.com/engine/install/linux-postinstall/)
