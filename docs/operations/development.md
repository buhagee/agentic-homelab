# Codex and OpenChamber on the home server

Use the dedicated development account for both harnesses. OpenChamber provides
OpenCode chat and a browser terminal; that terminal attaches to native Codex in
an independently supervised tmux session. The server remains headless. The
browser interface does not provide graphical desktop Computer Use.

This is an **opt-in installation**. Complete the first setup, provider login and
HTTPS acceptance below, then enroll the environment for managed updates. After
enrollment, successful platform deployments can update native runtimes, the shared
baseline and gateway while preserving active work and stopped-service intent.
Unconfigured hosts receive source files only.

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

Reviewed runtime pins are Codex `0.172.0`, OpenCode `2.4.2`, OpenChamber `2.8.1`,
OAuth2 Proxy `v7.15.6` and Caddy `2.11.9-alpine`. Native download hashes and npm
lock inputs live in `infrastructure/dev-agent` and are updated by Renovate (`scripts/maintenance/refresh-openchamber-release.py`) or `scripts/maintenance/update-native-runtime.py` (auto-merging patch and minor updates after `opencode-smoke` passes). Gateway image pins come from `versions.env`. Required upstream native install scripts are allowed. The known
npm `allowScripts` review warning is distinct from a failed native build:
version checks and an actual PTY spawn/input/resize/exit must still pass.

## 1. Prepare native services without starting them

From the reviewed repository checkout, first run the dry-run:

```sh
python3 scripts/setup/install-dev-agent.py
sudo python3 scripts/setup/install-dev-agent.py --apply
```

The first installation defaults to Node at `/usr/bin/node` and OpenChamber on
port `3939`. Later runs preserve both recorded settings. To select a different
Node executable, add `--node /opt/node/bin/node` to both the preview and apply
commands, using the actual path on your server. Use `--port` to select a new
OpenChamber loopback port.
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

Systemd treats OpenChamber's numeric exit code `143` as a clean shutdown.
An unsolicited exit with the same numeric code is indistinguishable and also
does not trigger a restart. Other failures, including SIGKILL and OOM kills,
remain subject to the service's bounded `Restart=on-failure` policy.

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

The initial shared MCP is the public Context7 endpoint. Configure personal
integrations in the native harness that uses them. An enabled MCP can make
outbound requests according to that client's normal tool policy.

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

### Install and verify the Oracle development route

Before starting the gateway, install the rendered `oracle-dev-route.yml` on the
Oracle host. It matches only the chosen HTTPS hostname at priority 150, above the
existing wildcard (100) and below platform status (200). It uses the existing
WireGuard upstream, TLS resolver and security middleware. Choose an unused
development hostname under the platform domain. The fragment lives outside the
automatic Oracle deployment and requires a deliberate operator installation.

On the home server, copy the nonsecret fragment to the Oracle operator using
your existing private administrative access. Substitute the SSH alias:

```sh
sudo cat /etc/qacey-dev/web/oracle-dev-route.yml | ssh ORACLE-SSH 'umask 077; cat > oracle-dev-route.yml'
```

On Oracle, verify the destination is absent on first install. On updates, first
stop the gateway and compare the installed digest with the one previously
verified. Use a staging file and rename it into the watched directory:

```sh
edge_dir=/opt/qacey/traefik/oracle/dynamic
sudo install -m 0644 -o root -g root "$HOME/oracle-dev-route.yml" "$edge_dir/.qacey-dev-edge.pending"
sudo mv -T "$edge_dir/.qacey-dev-edge.pending" "$edge_dir/qacey-dev-edge.yml"
sudo sha256sum "$edge_dir/qacey-dev-edge.yml"
```

Wait for the file provider to reload, then run the following in Bash on Oracle.
Set `dev_host` to your development hostname and `control_host` to the existing
logged platform hostname, such as Vaultwarden. Use the public HTTPS ingress. The proof header
confirms the exact router handled the request, even if the home gateway is still
offline. The positive control confirms subsequent requests reached the active
access log and the buffered writer flushed past the development probe.

```bash
(
  set -euo pipefail
  dev_host=REPLACE-WITH-DEVELOPMENT-HOST
  control_host=REPLACE-WITH-LOGGED-PLATFORM-HOST
  marker=$(openssl rand -hex 16)
  edge_dir=/opt/qacey/traefik/oracle/dynamic
  edge_log=/opt/qacey/traefik/oracle/logs/access.log
  before=$(sudo sha256sum "$edge_dir/qacey-dev-edge.yml")
  curl --silent --show-error --max-time 15 --dump-header - --output /dev/null \
    "https://$dev_host/?qacey_probe=dev-$marker" |
    tr -d '\r' | grep -Fxi "X-Qacey-Dev-Edge: $dev_host"
  curl --silent --show-error --max-time 15 --output /dev/null \
    "https://$control_host/?qacey_probe=control-$marker"
  # Give the buffered log writer later, harmless HEAD requests even on an idle site.
  for attempt in {1..120}; do
    if sudo grep -Fq "control-$marker" "$edge_log"; then break; fi
    curl --head --silent --show-error --max-time 10 --output /dev/null "https://$control_host/"
    sleep 1
  done
  sudo grep -Fq "control-$marker" "$edge_log"
  # Exit 1 means absent. Any read error or matching development marker fails.
  result=0
  sudo grep -Fq "dev-$marker" "$edge_log" || result=$?
  test "$result" -eq 1
  test "$before" = "$(sudo sha256sum "$edge_dir/qacey-dev-edge.yml")"
  printf 'Verified Oracle fragment: %s\n' "$before"
)
```

Proceed only when the check succeeds and the final digest matches the installed
fragment you reviewed. If log rotation occurred during the check, repeat with a
fresh marker. Keep requests free of credentials. Supply the verified Oracle
digest at each explicit gateway start. The home helper checks it against its
rendered fragment. The operator attests to the remote installation and marker
result; the home server cannot inspect Oracle's live configuration. Repeat
verification after edge logging or route changes. To roll back, first stop the
home gateway with `sudo qacey-dev-web stop`, then remove just this fragment on
Oracle with `sudo rm /opt/qacey/traefik/oracle/dynamic/qacey-dev-edge.yml` or
restore the previously verified version before restarting its matching gateway.

### Prepare local credentials

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
IdP access tokens are not substituted for OpenChamber authentication. Both the dedicated Oracle route and the home route opt out of Traefik access logs, OAuth request logs are disabled, and Caddy's HTTP
error-request logger is excluded because terminal/OAuth URLs may contain tokens.
Non-request startup diagnostics remain available.

The Compose project is **`qacey-dev-web`**, separate from `qacey-platform`.
The main platform's `up --remove-orphans` therefore does not own these containers.
Gateway provisioning installs `/etc/tmpfiles.d/qacey-dev-proxy.conf` so systemd
creates the adapter's bind-mount directory during early boot, before Docker
restores containers. The socket unit creates `backend.sock` later and sets its
owner and mode. An adapter that starts early can use the socket once it appears.
To apply the installed directory rule immediately on a running host, use
`sudo systemd-tmpfiles --create /etc/tmpfiles.d/qacey-dev-proxy.conf`.
Use the installed helper, which selects the local Docker socket and fixed project
explicitly, rather than inheriting a shell's `DOCKER_HOST`/`COMPOSE_*` overrides.

## 4. Activate, verify and open from the phone

Activation is an explicit operator step after reviewing the PR and configuration:

```sh
sudo systemctl daemon-reload
sudo systemctl start qacey-codex-tmux.service qacey-openchamber.service qacey-dev-proxy.socket
sudo qacey-dev-web start --verified-oracle-route VERIFIED-ORACLE-SHA256
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

For native Codex remote control, also enable `qacey-codex.service` if it is part
of your setup. Its login check requires a signed-in Codex account. Gateway
containers use `unless-stopped`, respecting an explicit stop. Systemd starts new
native processes after a reboot. Existing tmux sessions end with the old boot,
and saved Codex conversations can be resumed in a new session.

After a planned reboot, verify startup and then test the HTTPS sign-in flow:

```sh
for unit in qacey-openchamber.service qacey-dev-proxy.socket qacey-codex-tmux.service; do
  systemctl is-enabled "$unit"
  systemctl is-active "$unit"
done
systemctl is-active qacey-codex.service  # If native Codex remote control is enabled
sudo qacey-dev-web status
sudo -u dev-agent curl --fail --silent --show-error --max-time 5 --output /dev/null \
  --unix-socket /run/qacey-dev-proxy/backend.sock http://localhost/health
```

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

For persistent `qacey-dev codex PROJECT` sessions, put MCP values in the
development user's mode `0600` `~/.config/qacey-dev/mcp-env.json` file. It
accepts only names declared by a completed sync and string values. An MCP may
leave optional values unset. The public launcher diagnoses a shell-exported
declared name missing from the file before tmux is invoked. Each new Codex
process loads the current file under the development account. Reattaching
preserves the existing process environment. Restart the child deliberately to
load changed values. The foreground OpenChamber launcher also accepts declared
variables from its own environment, with file values taking precedence.
Reserved loader, harness and provider-login names are rejected.

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
completed sync is a no-op. Reconcile any active `~/.codex/AGENTS.override.md` before syncing global guidance.

With managed updates enrolled, a reviewed change to this baseline is applied by
Qacey's native reconciliation when the environment is idle. Changes to shared
configuration preserve the same conflict checks as manual sync. Authentication,
local additions and client-specific plugins remain owned by their native clients.
Pause managed updates before editing those configuration files manually.

## Managed updates through Qacey

Initial account provisioning, provider login, credentials and HTTPS activation
remain explicit operator steps. After confirming the initial native-service and
HTTPS acceptance checks, enroll the existing installation once. Subsequent successful Qacey deployments
reconcile the reviewed native helpers, runtime pins, shared configuration, service
units and gateway. The existing ten-minute reconciliation timer also retries a
deferred update when no further commit has been merged.

### Enroll the existing installation

Use the operator account that owns the platform deployment checkout, not
`dev-agent`. Ensure the existing
[reconciliation timer](deploy-runner.md#reconciliation-timer) is installed,
enabled and active; enrollment checks it but does not enable it. All three native
installation records must be ready, the dedicated identity must still match,
and both root credential files must pass validation. From a reviewed checkout,
substitute the digest from the successful Oracle marker check above:

```sh
sudo python3 scripts/setup/install-dev-autodeploy.py \
  --operator "$(id -un)" \
  --verified-oracle-route VERIFIED_SHA256

sudo python3 scripts/setup/install-dev-autodeploy.py \
  --operator "$(id -un)" \
  --verified-oracle-route VERIFIED_SHA256 \
  --apply

sudo qacey-dev-deploy status
```

The first command previews enrollment. The second installs the updater and its
root-owned policy; it does not start services or log in to providers. The default
source is `https://github.com/buhagee/agentic-homelab.git`, branch `main`. A reviewed
public GitHub fork can be selected with `--repository HTTPS_URL`. Credentials in
repository URLs and alternate branches are rejected.

Enrollment delegates only `qacey-dev-deploy apply COMMIT_SHA` to the deployment
operator. The updater independently fetches its fixed source into a private
root-owned Git store and accepts a fresh request only for the current `main` tip.
It runs privileged setup from that verified source. Runtime installation and
configuration sync run as the existing development account with no extra groups.
The development account receives no sudo permission. Merging changes to these
deployment scripts therefore authorizes their use by this enrolled privileged
path; review them accordingly.

On hosts using sudo-rs, a traditional sudoers argument regex is not portable.
The generated rule delegates only the root-owned helper's `apply` prefix. The
helper requires exactly one lowercase 40-character commit argument before it
opens policy or state. After installing the reviewed rule, test **as the
reconciliation operator**, from an independent maintenance terminal:

```sh
sudo -k -n /usr/local/sbin/qacey-dev-deploy apply invalid
```

The expected result is a nonzero exit with `Native development deployment:
invalid-revision`. This proves the real helper ran without authentication or
a cached ticket. An authentication error instead means delegation failed.
The invalid revision cannot start a deployment or write the journal.

If an **already enrolled** host cannot invoke its worker, use the independent
operator maintenance terminal. Inspect `sudo qacey-dev-deploy status` first.
Finish any open transaction using its recorded source. With no open transaction,
run the following from a verified, root-owned checkout of the reviewed main
revision, after it has merged:

```sh
sudo python3 -I -B scripts/setup/install-dev-autodeploy.py \
  --repair-helper "$(git rev-parse HEAD)" --apply
```

Repair fetches that exact main tip through the enrolled private source, checks
compatibility, and publishes the launcher before the parsed sudoers fragment.
It keeps the existing pause flag, drift baseline, route attestation and journal.
Repeat the uncached invalid-revision probe above, then let the timer perform
normal activity checks. Never clear a busy result to force an upgrade.

### What happens after a merge

The main platform deployment and health check finish first. A native failure
gets its own alert and does not change the platform result. With no transaction
in progress, the native updater can publish a compatible worker from the exact
verified main revision even while the application is busy. After the atomic
launcher switch it returns `helper-refreshed`; the next invocation runs the new
worker. A paused deployment stays paused. An open journal keeps its worker and
target. The worker compares application inputs with the last successful native deployment.
Documentation and unrelated platform changes do not reinstall runtimes or restart
native services. An unchanged input digest is a no-op, not a repair of runtime
drift. Changes to root-managed installation files are rejected for operator
review rather than silently adopted.

For changed inputs, the updater requires two idle observations, at least one
minute apart; the ten-minute timer normally supplies the second observation.
Running Codex processes, any managed tmux session including detached sessions,
OpenCode work, native terminals and supported queued or autonomous activity defer
the update. Unknown versions, unavailable probes and incomplete status also
defer it. Finish work and exit its terminal/session when ready: closing the
browser or detaching tmux does not necessarily make the environment idle.
The optional experimental `qacey-codex.service` must be stopped separately.

Before publication, the updater records service and gateway state, closes browser
ingress and checks activity again. It refreshes the reviewed installation, verifies
versions and application health, then restores only services and ingress that
were previously active. It preserves unit enablement and never restarts the
independent tmux server. An OpenChamber or gateway restart disconnects browser
connections; reconnect once the update has completed.

The pinned applications expose status snapshots, not an atomic maintenance lock.
The checks are conservative, but direct local clients or internal callbacks can
race with them. OpenChamber's auxiliary recap/suggestion generation may be
cancelled by its normal shutdown. Disable deliberate autonomous producers or
finish their work yourself; the updater does not change those preferences to
force an idle result.

The recorded Oracle digest can be reused only while the rendered edge fragment
is unchanged. An edge-route change blocks publication until the operator prepares
and verifies the new route and explicitly repeats enrollment with its digest.
The updater does not change Oracle or attest to its remote state.

### Pause, inspect and recover

```sh
sudo qacey-dev-deploy status
sudo qacey-dev-deploy pause
# Perform deliberate maintenance only after pause succeeds.
sudo qacey-dev-deploy resume
```

Pause and resume require the operator's administrative terminal. They share the
updater's lock; if an update is running, pause refuses instead of interrupting it.
A successful pause prevents subsequent native updates and retains any pending
transaction. Resume lets the next successful platform reconciliation retry.
Neither command changes the main platform deployment or starts native services.

Status reports desired and applied revisions/digests, the pause flag, a sanitized
reason and any interrupted transaction phase. Busy/unknown activity is a deferred
update. A failed native update alerts separately and leaves the healthy platform's
`last-good` revision intact; it does not roll back Qacey. After publication begins,
failures keep browser ingress closed and preserve the original lifecycle journal.
Recovery retries the recorded immutable source, even if `main` has since advanced,
before attempting a later deployment. It does not automatically downgrade mutable
application data. Inspect the local failure, correct its cause and let reconciliation
retry. Do not delete the journal to bypass a failed update. A broken recorded
release may require reviewed manual repair rather than a newer merge alone.

The updater's policy is `/etc/qacey-dev/deployment.json`; its private state and
verified source checkouts are under `/var/lib/qacey-dev-deploy`. Keep these records
through an interrupted update. If deliberately changing the installed account,
Node path, port, gateway settings or root-managed files, pause first, complete
manual maintenance, then repeat enrollment from a reviewed checkout. Enrollment
refuses an unfinished transaction and preserves the pause flag; explicitly resume
when maintenance is complete.

## Stop, revoke, update and recover

When managed updates are enrolled, pause them before planned manual maintenance
and wait for a successful pause. For urgent access revocation, stop the gateway
immediately, then pause the updater. If pause reports an update in progress, that
update may restore the previously active gateway: repeat the stop after pause
succeeds and verify it stays stopped. Restrict the development route at the edge
if access must remain blocked throughout an in-progress update. Inspect any
interrupted transaction before deliberately restoring access.

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

Stopping tmux ends its active Codex processes. Save work first. Stopping OpenChamber also removes the bridge socket and stops its forwarder.
If OpenChamber fails unexpectedly, the bridge closes. Browser requests cannot
start either prerequisite of the forwarder. After checking OpenChamber's
recovery and its managed backend, explicitly restore the bridge:

```sh
sudo systemctl start qacey-openchamber.service
sudo systemctl start qacey-dev-proxy.socket
```

The socket is a late member of `multi-user.target` and binds to OpenChamber.
Its ordering indicates the app unit has started, not that the HTTP backend is
ready. To migrate a socket enabled using the old early-boot unit, record whether
it was enabled, then run `sudo systemctl reenable qacey-dev-proxy.socket` after
installing the new units and reloading systemd, only if it was enabled and you
want to preserve boot startup. For a previously disabled socket, leave it
disabled.

For manual updates, record current service enablement/active states and finish affected
work. Stop the gateway, review new pins and package lock/hash changes, rerun root
preparation, install the matching runtimes as the account, then sync the reviewed
baseline. Run `systemctl daemon-reload` after unit changes. If changing the native port,
stop/restart the socket proxy service as well so it loads the new target. Restart only services
that were previously active and that you intend to restore. Root provisioning
never enables/restarts them. Update the gateway with an explicit `start` after repeating the Oracle marker check with its matching digest; this recreates its containers and disconnects remote sessions.

Retain previous version directories and the previous reviewed checkout/installed
record for rollback. Re-provision and select the previous reviewed release as a
unit: changing only a version string or the runtime selection file fails the
launcher consistency checks. Node-major changes need matching native addons.
If saved application state has migrated, assess its compatibility before a
runtime rollback; a version directory is not a backup of mutable data.

Back up uncommitted projects, shared guidance/skills, user sync state, private
client login/session data, and root installation/settings records. For an enrolled
updater, include its deployment policy and state journal; its verified Git source
is reproducible except that the exact source for an unfinished transaction must
remain available until recovery finishes. Encrypt any
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
- [ ] Stop OpenChamber while the gateway is up: the socket path disappears, the forwarder stops and a browser retry leaves the app stopped. Confirm the independent tmux/Codex session survives.
- [ ] Start OpenChamber, confirm the managed OpenCode child is ready, start the socket, then reconnect. Exercise unexpected service loss and the same bridge recovery in a maintenance window.
- [ ] Gateway stop cuts an already-open WebSocket; native jobs continue until deliberately stopped.
- [ ] After enrollment, a busy session defers native updating and the reconciliation timer retries after it is finished; an unrelated commit causes no native restart.
- [ ] Pause/resume work, stopped services stay stopped, and native failures leave the platform healthy while preserving an inspectable recovery journal.
- [ ] Boot/restart policy, explicit sudo handoff and encrypted backup/restore have been exercised.

See the [legacy agent retirement runbook](../../scripts/deploy/README.md#legacy-agent-retirement) for the Docker cutover and retained data.

**Merge consequence:** pushes to `main` and the reconciliation timer can invoke
the existing platform deployment pipeline. Native updates run after a successful
platform health check only on hosts explicitly enrolled above. An unenrolled host
receives the source changes without native account creation, login or activation.

## Optional operational access

After initial host acceptance, see [native development operations](dev-operations.md)
for scoped production diagnostics, explicitly authorized container actions and a
separate rootless development-container engine. Neither capability is enabled by
the standard native installation or automatic updates.

## References

- [Codex skills](https://learn.chatgpt.com/docs/build-skills.md)
- [OpenCode skill discovery](https://opencode.ai/docs/skills/)
- [OpenCode MCP configuration](https://opencode.ai/docs/mcp-servers/)
- [OpenChamber 2.8.1](https://github.com/openchamber/openchamber/releases/tag/v2.8.1)
- [OAuth2 Proxy configuration](https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/)
- [Caddy reverse proxy and Unix upstreams](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- [Compose raw env files](https://docs.docker.com/reference/compose-file/container-spec/)
- [Traefik per-router observability](https://doc.traefik.io/traefik/v3.8/reference/routing-configuration/http/routing/observability/)
- [Traefik access logs](https://doc.traefik.io/traefik/v3.8/reference/install-configuration/observability/logs-and-accesslogs/)
- [systemd unit relationships](https://www.freedesktop.org/software/systemd/man/257/systemd.unit.html)
- [systemd socket dependencies](https://www.freedesktop.org/software/systemd/man/257/systemd.socket.html)
- [systemd socket proxy](https://www.freedesktop.org/software/systemd/man/latest/systemd-socket-proxyd.html)
