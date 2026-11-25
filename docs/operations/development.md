# Codex and OpenChamber on the home server

Use the dedicated development account for both harnesses. OpenChamber provides
OpenCode chat and a browser terminal; that terminal attaches to native Codex in
an independently supervised tmux session. The server remains headless. The
browser interface does not provide graphical desktop Computer Use.

This is an **opt-in installation**. Merging publishes the files through the
existing platform pipeline; it does not install native runtimes, apply user
configuration, start services or remove Hermes/the existing Docker OpenCode.
The [design](../designs/2026-11-26-shared-development.md) records the boundaries.

## What is shared

| Concern | Shared source or behaviour |
| --- | --- |
| Projects and Git | Independent clones under the dedicated account's `~/projects`; one writer per worktree. |
| Project instructions | Each repository's `AGENTS.md`. |
| Global instructions | `~/.config/qacey-dev/AGENTS.md`, linked from Codex and OpenCode. |
| Portable skills | Global `~/.agents/skills` and project `.agents/skills`; both pinned runtimes discover these directly. |
| Common MCPs | `infrastructure/dev-agent/shared/mcp.json`, adapted into native Codex TOML and OpenCode V2 JSON. |
| Model, permission and plugin settings | Owned by each client, preserved during shared sync. |
| Login, OAuth registrations and history | Owned by each client; no shared authentication files or conversation databases. |

OpenChamber is an interface to OpenCode, not an additional independent harness.
Use its terminal for Codex. There is no A2A bridge: a Git branch and a concise
handoff note are enough to switch development tools without transferring a
private transcript or introducing another always-running agent.

Both harnesses run as the same Linux UID. They can therefore read that user's
files; separate login stores are an organisational boundary, not OS isolation.
The account has no sudo, Docker, audio/video or administrative group membership.
For privileged operations, have the agent prepare the command and run it in your
own sudo-authorised terminal. Never provide the password through chat or the
agent's terminal. Keep existing operator `~/projects` checkouts unchanged: some
may be live deployment roots. Create worktrees only from independent development
clones, never from the operator's production Git metadata.

## Prerequisites

- Complete the account, Codex installation and login steps in the
  [Codex foundation runbook](codex.md#1-review-and-provision-the-account).
  The existing experimental remote-control/pairing service is optional and is
  not required for this HTTPS route.
- Linux/systemd, Python 3.11+, Git, tmux, and
  `/usr/lib/systemd/systemd-socket-proxyd` (the Debian/Ubuntu location).
- glibc Linux x64 or arm64, Node **>=24.14.0** and npm. Provide the absolute
  Node path at provisioning. Native package scripts compile/load `node-pty`;
  install the normal compiler/Python prerequisites if its prebuild is unavailable.
  Node major upgrades need a fresh runtime installation. Actual package acceptance
  here covers x64; verify native PTY operation separately on arm64.
- Rootful Docker with the existing `qacey-proxy` network, and Docker Compose
  **>=2.30.0** for raw credential env files. The Unix socket adapter uses the host
  numeric UID/GID; a daemon using user namespace remapping requires a separately
  reviewed mapping and is not covered by this installation.
- The existing Oracle/WireGuard/home-Traefik ingress, a chosen development DNS
  hostname and its TLS certificate resolver. Keep SSH private. Do not open
  OpenChamber's port or OpenCode's managed backend to the LAN/Internet.
- An OIDC application with callback `https://YOUR-HOST/oauth2/callback`, exact
  verified email allowlist and **mandatory MFA enforced at the identity provider**.
  Setting `mfa_required: true` is an operator attestation; this repository cannot
  inspect the provider's MFA policy. SSO by itself does not prove MFA.

Reviewed runtime pins are Codex `0.172.0`, OpenCode `2.4.1`, OpenChamber `2.8.0`,
OAuth2 Proxy `v7.15.6` and Caddy `2.11.9-alpine`. Native download hashes and npm
lock inputs live with the runtime assets; gateway image pins come from
`versions.env`. Required upstream native install scripts are allowed. The known
npm `allowScripts` review warning is distinct from a failed native build:
version checks and an actual PTY spawn/input/resize/exit must still pass.

## 1. Prepare native services without starting them

From the reviewed repository checkout, first run the dry-run:

```sh
python3 scripts/setup/install-dev-agent.py --node /usr/bin/node
sudo python3 scripts/setup/install-dev-agent.py --node /usr/bin/node --apply
```

Use the same `--node` arguments for both commands if Node lives elsewhere. The
optional `--port` changes only the OpenChamber loopback port (default `3939`).
The installer consumes `/etc/qacey-codex/installation.json` and reuses its
account/home; the examples use the default `dev-agent`, but substitute the
recorded account when it differs. It installs no users/groups or credentials.

Root-owned helpers are under `/usr/local/lib/qacey-dev`, with launcher
`/usr/local/bin/qacey-dev`. `/etc/qacey-dev/installation.json` records the identity,
source revision, Node path, port and versions. Four units are installed disabled:

| Unit | Ownership |
| --- | --- |
| `qacey-openchamber.service` | OpenChamber and its one private loopback OpenCode child. |
| `qacey-codex-tmux.service` | Independent foreground tmux server and persistent Codex sessions. |
| `qacey-dev-proxy.socket` | Mode `0600` Unix socket owned by the recorded development account. |
| `qacey-dev-proxy.service` | Socket-activated forwarding to loopback OpenChamber. It does not start a deliberately stopped app. |

The pinned OpenCode policy preserves unrelated OpenChamber policy keys. Native
launch rejects shared OpenCode service mode and leaves backend-port/adoption
variables unset. Passive relay startup is disabled; this is not a network ban on
an agent that already has ordinary development network access.

## 2. Install runtimes and the shared baseline as the account

```sh
sudo -iu dev-agent
qacey-dev install-runtime
qacey-dev install-runtime --apply
qacey-dev sync
qacey-dev sync --apply
qacey-dev status
exit
```

Both commands preview by default. Runtime installation verifies SHA-256 before
extracting official releases, installs the reviewed production npm lock, and
checks the actual CLI versions and native PTY binding before publishing a
selection. Packages remain in versioned directories under
`~/.local/share/qacey-dev/runtime`. OpenChamber's directory includes the Node
major to avoid reusing an incompatible native addon. This is version discipline
within a user-owned runtime, not an immutable security boundary.

The initial shared MCP is the public Context7 endpoint. Personal Google,
Intervals.icu and other Hermes integrations are not copied. An enabled MCP can
make outbound requests according to that client's normal tool policy.

Codex uses its own `qacey-codex login` device flow. OpenCode uses its own provider
connection in OpenChamber settings. Sign in deliberately under the dedicated
account; do not copy the operator's credentials. Subscription sign-in and API
keys are different billing routes. An API key used by OpenCode must have its own
valid API credit/billing entitlement; this setup does not convert subscription
usage into API credit.

## 3. Prepare the HTTPS gateway and credentials

Copy `infrastructure/dev-agent/web/settings.example.json` to a local nonsecret
settings file and replace every example hostname/client/email/resolver. The file
has exactly six fields: `hostname`, `issuer`, `client_id`, `emails`,
`cert_resolver`, `mfa_required`. Use a dedicated OIDC client and ensure its issuer
publishes discovery metadata. Confirm its mandatory MFA policy before setting
`mfa_required` to `true`.

```sh
python3 scripts/setup/install-dev-web.py --settings /path/to/dev-settings.json
sudo python3 scripts/setup/install-dev-web.py --settings /path/to/dev-settings.json --apply
```

This renders root-owned, nonsecret files under `/etc/qacey-dev/web` and installs
`qacey-dev-web`. It does not contact the IdP, create secrets or start containers.
The assets are snapshots independent of a resettable deployment checkout.
Managed edits are detected: change the source/settings and re-provision instead
of silently editing rendered files. A partial publication can finish the same
version; a conflicting version or later managed edit must be reconciled first.

Create these files in your administrative terminal, owned by root with mode
`0600`, then edit them locally. On the **first installation only**, this command
creates empty files and refuses to overwrite existing ones:

```sh
sudo sh -c 'umask 077; set -eC; : > /etc/qacey-dev/web/oauth2.env; : > /etc/qacey-dev/openchamber.env'
sudoedit /etc/qacey-dev/web/oauth2.env /etc/qacey-dev/openchamber.env
```

| File | Exactly these keys |
| --- | --- |
| `/etc/qacey-dev/web/oauth2.env` | `OAUTH2_PROXY_CLIENT_SECRET` from the IdP; `OAUTH2_PROXY_COOKIE_SECRET`, URL-safe base64 encoding of 32 random bytes. |
| `/etc/qacey-dev/openchamber.env` | Independent `OPENCHAMBER_UI_PASSWORD` and `OPENCODE_PASSWORD`, each at least 24 characters. |

Use one `KEY=value` per line. The OAuth file uses Compose's **raw** format:
quotes and dollar signs are literal parts of the secret; do not add shell quotes
around a value. The native systemd file uses a deliberately restricted unquoted
base64/URL-safe alphabet, avoiding differences between systemd and shell parsing.
Generate each native password separately with `openssl rand -base64 32` in your
own terminal. Generate the OAuth cookie secret with URL-safe base64 (ordinary
base64 can contain `+` or `/`, which this OAuth2 Proxy release does not decode):

```sh
python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
```

Do not paste credentials into a PR, chat, command argument or log.
Do not add other environment keys: the activation check rejects overrides such
as email-domain/route bypasses and `OPENCODE_JWT_SECRET`.

```sh
sudo qacey-dev-web check
```

`check` verifies root ownership/modes, allowed keys, complete settings, Compose
version and `docker compose config --quiet`; it never prints credential values
or starts anything. This is configuration validation, not a live MFA/TLS test.

### Ingress path

Traefik exposes only OAuth2 Proxy on `websecure`. OAuth2 Proxy validates the
OIDC identity and exact email allowlist, then forwards over a private internal
Docker network to Caddy. Caddy reaches a protected Unix socket, which bridges to
loopback OpenChamber. Containers publish no ports, use no host networking and
receive no Docker socket. Caddy is the only gateway process with the dedicated
UID/GID and socket access; OAuth runs under a distinct unprivileged UID.

Caddy is needed because this pinned OAuth2 Proxy release uses a separate
WebSocket transport that cannot directly use its Unix HTTP dialer. It preserves
OpenChamber's Authorization header, canonical HTTPS/Host, streaming and terminal
WebSockets; wrong origins and mutation/WebSocket requests without Origin are
rejected. There are no unauthenticated application-route or trusted-IP bypasses.
IdP access tokens are not substituted for OpenChamber authentication. This router
opts out of Traefik access logs, OAuth request logs are disabled, and Caddy's HTTP
error-request logger is excluded because terminal/OAuth URLs may contain tokens.
Non-request startup diagnostics remain available. Keep any additional upstream
access logging subject to the same URL-token handling policy.

The Compose project is **`qacey-dev-web`**, separate from `qacey-platform`.
The main platform's `up --remove-orphans` therefore does not own these containers.
Use the installed helper, which selects the local Docker socket and fixed project
explicitly, rather than inheriting a shell's `DOCKER_HOST`/`COMPOSE_*` overrides.

## 4. Activate, verify and open from the phone

Activation is an explicit operator step after reviewing the PR and configuration:

```sh
sudo systemctl daemon-reload
sudo systemctl start qacey-codex-tmux.service qacey-openchamber.service qacey-dev-proxy.socket
sudo qacey-dev-web start
sudo qacey-dev-web status
sudo -iu dev-agent qacey-dev status
```

`start` checks the native services and exact socket owner/mode, then recreates
only this gateway's containers so replaced bind-mounted config files actually
load. **An explicit gateway start/update disconnects existing browser sessions
and terminal WebSockets.** Native tmux sessions remain running. Initial `start`
does not enable native boot startup; after acceptance, opt in deliberately:

```sh
sudo systemctl enable qacey-codex-tmux.service qacey-openchamber.service qacey-dev-proxy.socket
```

Gateway containers use `unless-stopped`, respecting an explicit stop. The native
processes do not survive a reboot; saved Codex conversations can be resumed after
starting a new session. Reconnection should never be described as reboot-proof
process persistence.

Open the HTTPS hostname on your phone, complete IdP MFA, then authenticate to
OpenChamber with its UI password. Enrol a passkey if desired. OpenCode chat is
available in the main UI. In the web terminal:

```sh
qacey-dev codex "$HOME/projects/agentic-homelab"
```

This attaches to a deterministic per-project tmux session, creating it if needed
on the separately running server. Another attachment to that project shares the
same session. The client cannot auto-start an unmanaged tmux server; start the
service if it is unavailable. Choose independent worktrees for concurrent tasks.

## Switching harnesses and evolving tooling

Finish or pause the current writer before changing harness. Keep a short
repo-local handoff note with goal, branch/worktree, relevant files, completed
validation and the next action. Open the same development worktree in the other
harness. The working files and committed decisions persist; reasoning history,
client approvals and conversation state do not transfer automatically.

Experiment through native settings/UI when useful. OpenChamber-installed MCPs,
plugins and models remain OpenCode-local until intentionally promoted. To share
a portable skill, place its reviewed `SKILL.md` directory in `.agents/skills` at
the intended global or project scope. Do not duplicate a skill that a client
plugin already owns; plugin hooks/runtime APIs are not cross-client standards.
Keep the [approved Superpowers/Gstack policy](agent-tooling.md), using each
client's native installation where runtime hooks are required.

Promote a common MCP by reviewing a change to `shared/mcp.json`. Schema 1 accepts
named `servers` with `transport: stdio|http`, optional `enabled`, stdio `command`,
`args`, absolute `cwd`, `env_vars`, or HTTP `url`, `bearer_token_env_var` and
`env_http_headers`. `{home}` expands in stdio command/arguments/cwd only. Secrets
are environment references, never literal manifest values. Unsupported/unknown
fields and JSONC are rejected rather than guessed.

Shared MCP variables can be supplied in a user-owned mode `0600` file
`~/.config/qacey-dev/mcp-env.json`. It contains only declared variable names and
string values. The launcher rejects reserved loader, harness and provider-login
names. This file is not a way to override HOME/PATH, inject shell startup, or
share provider credentials. Values load in the actual Codex/OpenChamber child,
so a persistent tmux server does not retain stale MCP environment values. Restart
or resume the relevant child deliberately after changing its environment.

Before applying a baseline, stop native configuration editors. They do not
participate in the sync lock. Review the source Git diff and run:

```sh
qacey-dev sync --source /path/to/reviewed/shared
qacey-dev sync --source /path/to/reviewed/shared --apply
```

The preview lists paths and managed server names; it does not dump native configs
or secrets. Unmanaged local fields survive. A changed previously managed value
causes a conflict. Resolve it by reconciling the reviewed baseline/client change,
not deleting the sync state or forcing an overwrite. An interrupted apply resumes
only for the same baseline with unchanged before/after files. Repeating a
completed sync is a no-op.

Qacey auto-deploy is useful for distributing the reviewed source. It deliberately
does not apply personal configuration, upgrade runtimes, install every plugin or
restart coding sessions. These remain separate lifecycle operations.

## Stop, revoke, update and recover

```sh
sudo qacey-dev-web stop
```

This stops only containers labelled for the gateway project and cuts current
remote HTTP/WebSocket connections, even when gateway settings or credentials
have become invalid. It leaves native Codex jobs running. OAuth cookies are
Secure/HttpOnly/SameSite Lax with a two-hour expiry and 30-minute refresh; refresh
can extend a session. Logout/expiry does not necessarily close an already-upgraded
WebSocket or cancel background jobs. Revoke the IdP session and rotate credentials
as appropriate before explicitly starting again. When rotating the native
OpenChamber/backend passwords, explicitly restart `qacey-openchamber.service`
to load its new environment; the separate tmux service can keep running.

To stop native web/backend processes or all running Codex sessions respectively:

```sh
sudo systemctl stop qacey-openchamber.service
sudo systemctl stop qacey-codex-tmux.service
```

Stopping tmux ends its active Codex processes. Save work first. The gateway bridge
does not restart an intentionally stopped native application.

For updates, record current service enablement/active states and finish affected
work. Stop the gateway, review new pins and package lock/hash changes, rerun root
preparation, install the matching runtimes as the account, then sync the reviewed
baseline. Run `systemctl daemon-reload` after unit changes. If changing the native port,
stop/restart the socket proxy service as well so it loads the new target. Restart only services
that were previously active and that you intend to restore. Root provisioning
never enables/restarts them. Update the gateway with an explicit `start` after
`check`; this recreates its containers and disconnects remote sessions.

Retain previous version directories and the previous reviewed checkout/installed
record for rollback. Re-provision and select the previous reviewed release as a
unit: changing only a version string or the runtime selection file fails the
launcher consistency checks. Node-major changes need matching native addons.
If saved application state has migrated, assess its compatibility before a
runtime rollback; a version directory is not a backup of mutable data.

Back up uncommitted projects, shared guidance/skills, user sync state, private
client login/session data, and root installation/settings records. Encrypt any
backup containing credentials, including root secret files. Restore the dedicated
UID/GID, private home/secret permissions and root records together; do not copy
these credentials into another user. Existing platform backups do not automatically
include the new home. Rebuild reproducible runtime caches where practical.

## GitHub Codex reviews

Use the native [Codex GitHub integration](https://learn.chatgpt.com/docs/third-party/github):
select this repository in [code-review settings](https://chatgpt.com/settings/code-review)
and enable personal automatic reviews with the desired trigger. Account settings
are separate from repository files. The owner has reported enabling auto reviews;
confirm a Codex review actually appears on an eligible subsequent PR/update.
An explicit `@codex review` tests a manual invocation, not the automatic trigger.

Root `AGENTS.md` contains `Code Review Rules` for infrastructure side effects,
authentication and upgrade preservation. **No OpenAI API key or additional GitHub
Actions secret is needed for native Codex reviews.** Retain normal CI and branch
protections; a Codex review is an additional review signal, not a deployment gate
replacement. Provider/API keys for OpenCode and OIDC credentials above serve
different purposes and should not be added to GitHub for this review setup.

## Acceptance before retiring the old stack

Repository tests cover temporary filesystem behaviour and fail-closed rendering.
CI additionally checks real pinned package/version/config/skill interfaces,
native PTY behaviour, standalone Compose syntax and a disposable Unix
HTTP/WebSocket proxy. These checks do not prove the live server's deployment.

- [ ] Correct account, private home, no privileged supplementary groups, expected runtime versions.
- [ ] DNS and trusted TLS through the existing ingress; SSH stays private.
- [ ] Unauthenticated/wrong-email identities cannot reach application or terminal; MFA is required.
- [ ] Neither loopback web/backend port is reachable from the LAN or Internet; adapter has no published port.
- [ ] Wrong-Origin and missing-Origin terminal/mutation requests fail; OpenChamber bearer-authenticated requests succeed.
- [ ] OpenChamber reports its managed OpenCode child ready, not merely HTTP health; provider login stays private.
- [ ] Phone terminal input/resize/reconnect, approval display and ordinary edit/build/test work.
- [ ] Restart OpenChamber and reconnect: the independently owned tmux/Codex process survives.
- [ ] Gateway stop cuts an already-open WebSocket; native jobs continue until deliberately stopped.
- [ ] Boot/restart policy, explicit sudo handoff and encrypted backup/restore have been exercised.

Only after acceptance should a separate cleanup PR retire Hermes, personal MCPs,
seed interaction and duplicated configuration. Preserve useful old OpenCode state
before removing its existing parent directories.

**Merge consequence:** pushes to `main` and the reconciliation timer can invoke
the pre-existing platform deployment pipeline. This PR's native/gateway setup is
not called by that pipeline, but schedule the merge with the existing deployment
behaviour in mind.

## References

- [Codex skills](https://learn.chatgpt.com/docs/build-skills.md)
- [OpenCode skill discovery](https://opencode.ai/docs/skills/)
- [OpenCode MCP configuration](https://opencode.ai/docs/mcp-servers/)
- [OpenChamber 2.8.0](https://github.com/openchamber/openchamber/releases/tag/v2.8.0)
- [OAuth2 Proxy configuration](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/)
- [Caddy reverse proxy and Unix upstreams](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- [Compose raw env files](https://docs.docker.com/reference/compose-file/container-spec/)
- [systemd socket proxy](https://www.freedesktop.org/software/systemd/man/latest/systemd-socket-proxyd.html)
