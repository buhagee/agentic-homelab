# Additive Linux Codex foundation

Status: implementation approved by the owner on 2026-11-26; host activation is a separate operation.

## Goal

Provide a usable, opt-in native Codex development environment while the existing
platform continues operating. ChatGPT becomes the personal and design interface;
Hermes retirement and optional OpenChamber adoption follow in separate changes.

## Deployment evidence and workspace decision

The private `buhagee/homeserver-deploy` repository contains a deploy-only workflow
which calls the root-owned `homeserver-deploy` dispatcher. The dispatcher in this
repository switches to the existing operator account. `auto-deploy.sh` defaults
to `$HOME/projects/qacey-platform`, while the dispatcher installer embeds its
own checkout location and the operations guide also shows `/srv/agentic-homelab`.
These sources do not establish the effective path on the live host.

The owner confirms projects are under their `~/projects` and may run from there.
Treat existing checkouts as potentially live. Do not recursively grant access,
change ownership, move them, or use linked worktrees whose common Git directory
belongs to a live checkout. Start with fresh remote clones in the dedicated
account's own `projects` directory. Worktrees of those development clones are
appropriate for parallel tasks.

Opening a PR does not deploy. Merging to `main` can trigger the existing dispatch
and reconcile deployment paths, even for this additive change. This feature must
not be called by Compose, deployment, first-time setup or the existing timers.

## Account and installation contract

- Default dedicated account: `dev-agent`; default home: `/home/dev-agent`.
- Allow an explicit alternate absolute home such as `/mnt/ssd/dev-agent` on a
  verified SSD mount. Keep it outside `/mnt/ssd/qacey`, which platform setup
  recursively assigns to the operator. Require existing root-owned ancestors
  with group and other search permission and no group or other write permission.
  Reject ambiguous, dangerous or symlinked paths. Do not adopt an unrelated
  existing account or home. Reruns recognize this installation's root-owned record.
- Root provisioning is dry-run by default, with writes only on `--apply`.
- Provision a normal locked-password account with its own primary group, no
  supplementary groups, and no sudoers/Docker-socket grant.
- Create only that account's own `projects`, `.codex` and user-tool directories.
  Protect state and home with restrictive ownership/modes. Never read/copy the
  operator's credentials, `.env` files or existing project contents.
- Install root-owned helpers under `/usr/local/lib/qacey-codex`, a launcher at
  `/usr/local/bin/qacey-codex`, an installation record at
  `/etc/qacey-codex/installation.json`, and a disabled system unit named
  `qacey-codex.service`. Use fixed system destinations and reject symlink or
  unowned collisions before writing. Do not enable/start/restart services.
- Seed user config and global guidance only when absent. Preserve edits and
  authentication on rerun. Updates to this installation's root-owned helper
  files are allowed when the operator explicitly reruns provisioning.
- Runtime download/install is a separate non-root action by the dedicated user.
  It must reject root and the wrong user before network or execution.

## Pinned runtime

Use stable Codex `0.172.0` (released 2026-11-24), not the alpha available in the
review environment. Use the complete official package through the official
installer; managed remote bootstrap needs the packaged helpers.

For this initial release, pin the reviewed official installer as well:

- URL: `https://chatgpt.com/codex/install.sh`
- SHA-256: `b698d8eb50c0fbe0214ea57b5bf2af439054108404c6d2b872989db02f4bd574`

The runtime helper defaults to dry-run. On `--apply`, download to a private
temporary directory, verify the hash before executing, then invoke
`sh <downloaded-file> --release 0.172.0` as the dedicated user with
`CODEX_NON_INTERACTIVE=1`, the installation's `CODEX_HOME`, and
`CODEX_INSTALL_DIR` pointing to its user bin directory. Prepend that bin to PATH
so the upstream installer need not edit shell startup files. Never pipe a remote
script into a root shell. The upstream installer verifies package checksums.
An upstream installer change must fail closed and require a reviewed pin update.

Verify the installed binary reports the exact expected version. No login,
remote-control start/pair, or service activation belongs in either installer.

## Launcher contract

`qacey-codex` uses the same recorded account, home, state and binary for every
operation. It rejects root and a different account. It does not source platform
environment files. Expose only these operations:

| Operation | Behaviour |
| --- | --- |
| `install-runtime [--apply]` | Run the separate pinned runtime installer; default dry-run. |
| `version` | Run `codex --version`. |
| `login` | Run `codex login --device-auth`; interactive, explicitly invoked. |
| `login-status` | Run `codex login status`. |
| `run PROJECT` | Validate an explicit development Git checkout and run `codex -C PROJECT`. |
| `start` | Run `codex remote-control start --json`. |
| `stop` | Run `codex remote-control stop --json`. |
| `pair` | Run `codex remote-control pair`. |
| `status` | Passively probe `codex app-server daemon version`. |

`run` resolves symlinks and requires both the selected working tree and its
common Git directory to be under the dedicated development root. Clear inherited
Git path override variables for that validation. Do not accept arbitrary forwarded
Codex flags that silently override the checked working directory. Spaces in valid
paths must work. These launcher checks are not a claim that a remote client has
the same launcher validation; the dedicated OS identity remains the host boundary.

## Development policy

Use documented workspace sandbox settings rather than combining legacy settings
with beta named profiles:

```toml
approval_policy = "on-request"
approvals_reviewer = "user"
sandbox_mode = "workspace-write"
cli_auth_credentials_store = "file"

[sandbox_workspace_write]
network_access = true
writable_roots = ["<dedicated-home>/projects"]
```

Do not hardcode a model or a ChatGPT workspace ID. Ordinary project edits, tests,
builds and dependency downloads should proceed without repeated per-file prompts.
Network access is intentionally enabled, not restricted by an unenforced domain
list. Linux permissions still apply. The account has no administrator or production
Docker access. For a privileged action, prepare the exact command and let the owner
run it in their sudo-authorized SSH terminal; passwords never enter agent input.

Use the existing selected Superpowers/Gstack workflow. Do not auto-install a broad
skill catalog or reuse OpenCode-generated registrations in Codex. Installation of
the selected native skills is explicit under the dedicated account, with one owner.

## Remote lifecycle

Install a disabled system-level `Type=oneshot`, `RemainAfterExit=yes` unit running
as the dedicated account. Use launcher `login-status` as `ExecCondition`, `start`
as `ExecStart` and `stop` as `ExecStop`. Use restrictive umask and bounded timeouts.
Do not add generic private-tmp/namespace restrictions without verifying socket and
Codex sandbox compatibility. There is no daemon health-supervision promise:
`systemctl is-active` records the start action, while launcher `status` probes the
actual daemon. The administrator enables the service only after manual sign-in.

Allow 900 seconds for stop to cover the lifecycle lock and graceful shutdown.
An intentional rollback stops the managed daemon and persists remote control as
disabled for later daemon starts. For an initialized installation, update the
separate managed daemon package from the explicitly selected CLI package.

This managed lifecycle is deliberate: in stable 0.172.0 the foreground
`remote-control --no-daemon` path uses a different socket from the normal `pair`
command. Do not combine that foreground command with a purported working pairing
runbook. Phone pairing, approvals, reconnect and reboot remain host acceptance tests.

## Verification and rollout

Tests must run offline with temporary paths and controlled OS/process adapters.
Cover dry-run/no writes, non-root runtime install, wrong account, existing state,
path/symlink collisions, checksum failure before execution, correct noninteractive
version pin, project paths with spaces, and linked Git metadata outside the dev root.
Keep tests in `scripts/setup/tests`, already included by `scripts/testing/run-all.sh`.

No production smoke/deploy command is part of validation. The owner reviews and
merges the PR; host installation, sign-in and activation are separate documented
steps. A later cleanup removes Hermes and obsolete personal MCPs, preserving the
OpenCode home currently located below `/mnt/ssd/qacey/hermes/opencode-v2`.

## Primary references

- [Codex stable release](https://github.com/openai/codex/releases/tag/rust-v0.172.0)
- [Official installer](https://chatgpt.com/codex/install.sh)
- [Authentication](https://learn.chatgpt.com/docs/auth)
- [Developer commands](https://learn.chatgpt.com/docs/developer-commands)
- [Stable remote-control source](https://github.com/openai/codex/blob/rust-v0.172.0/codex-rs/cli/src/remote_control_cmd.rs)
- [Stable daemon source](https://github.com/openai/codex/blob/rust-v0.172.0/codex-rs/app-server-daemon/src/lib.rs)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
