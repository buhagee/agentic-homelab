# Shared native development and HTTPS access

## Decision and scope

The operator has approved adding OpenChamber alongside native Codex on the
headless home server. Both execute as the existing dedicated development account
(default `dev-agent`), using its independent `projects` clones. This extends the
additive Codex foundation; it supersedes that design's deferral of OpenChamber.
Keep Hermes and the existing containerised OpenCode installation operational in
this PR. Do not merge, activate services, move production projects, or copy the
operator's credentials as part of preparing the change.

Use one HTTPS browser entry point: OpenChamber supplies OpenCode chat and a real
terminal in which the operator can attach to native Codex. OpenChamber is an
OpenCode interface, not a second OpenCode replacement and not a Codex chat UI.
No desktop, public SSH, A2A broker, or custom chat transport is required. A
headless browser may be automated through a project-local Playwright CLI/skill;
this does not provide native graphical desktop Computer Use.

## Share the contract, keep client adapters small

| Concern | Owner |
| --- | --- |
| Projects, Git branches and handoff notes | Independent development clones under the recorded account home |
| Project guidance | Repository `AGENTS.md` |
| Global guidance | `~/.config/qacey-dev/AGENTS.md`, linked from both native global entry points |
| Portable skills | `~/.agents/skills` and repository `.agents/skills` |
| Common MCP definitions | Versioned nonsecret `shared/mcp.json`, rendered into client-native configuration |
| Model choices, permissions and client plugins | Each harness's native configuration |
| Authentication, OAuth registration and conversation history | Each harness's own state; never symlink or copy between them |

Same-account processes can read that account's files; separate credential stores
are organisation, not an OS security boundary. Do not add sudo, Docker, audio,
video or other privileged group membership. Root tasks remain explicit commands
for the operator's own sudo terminal.

The baseline lives in this repository under `infrastructure/dev-agent/shared`.
The provisioner installs a snapshot beside root-owned helpers; `qacey-dev sync`
can also select an explicit `--source` directory. The default is a dry-run. An
apply preserves unrelated native settings, MCP servers, UI additions and user
edits. Track previously managed values, refuse conflicting edits, and make an
unchanged repeat a no-op. Treat partial/interrupted application as a recoverable
error rather than overwriting subsequent user changes. Do not print config
contents or secret values in the plan output. Report paths and managed names.

Only portable MCP fields are shared: stdio argv, cwd, environment-variable names,
HTTP URL, environment-backed headers/bearer token, enabled state. Literal secrets
do not belong in the manifest. Reject unknown fields, malformed names/URLs,
unsupported JSONC configurations and conflicting client overrides explicitly.
Initially share the public Context7 endpoint only. Do not import Docker-only
hostnames or Hermes's personal-service integrations.

For env-backed MCPs, the launcher reads only the names recorded by a completed
sync. Forward those explicitly allowed variables and optionally load their values
from user-owned mode0600 `~/.config/qacey-dev/mcp-env.json`. Never use that file
to override HOME/PATH, loader/shell settings or harness/provider authentication.
Load it inside the actual Codex/OpenChamber process launcher so a persistent tmux
server does not retain stale credentials or expose them through command arguments.

Codex uses `[mcp_servers.<name>]`; OpenCode V2 uses `mcp.servers.<name>`, `type`,
argv `command`, and `disabled`. Preserve client-specific OAuth settings and
permission/model/plugin choices. Existing Codex foundation guidance may be
migrated to the shared file only when unmodified; otherwise stop with a useful
conflict. Native global guidance must resolve to the same file after sync.

Both runtimes discover `.agents/skills` natively. Do not duplicate skills into
client-specific directories or symlink plugin runtime/auth directories. An
OpenChamber UI-installed MCP, skill or plugin remains client-specific until
intentionally promoted. Keep the existing Superpowers integrations and curated
Gstack lenses; do not bulk-install their directories or enable Gstack browser,
shipping, deployment or outside-review tools.

## Runtime and session ownership

Root provisioning and nonroot runtime installation are separate, dry-run by
default, and require `--apply` to write. Reuse the root-owned Codex account record
instead of hard-coding a username or home. Never install into an unrelated account
or follow a user-controlled destination symlink while privileged.

Pin OpenCode `2.4.1` and OpenChamber `2.8.0` to verified release assets and SHA256
hashes. OpenChamber requires Node >=24.14.0 and a separate OpenCode binary for
this release. Document/check the Node prerequisite and native dependency build
requirements. Install into private versioned user directories, verify versions,
then publish launchers without silently replacing unrelated binaries. Keep
transitive npm dependency resolution locked when feasible; report the remaining
trust boundary if upstream installation scripts must run. No runtime download,
provider login or service start is part of root provisioning.

Run OpenChamber foreground as the account, listening only on `127.0.0.1` (default
port `3939`, configurable at provisioning). Point it at the pinned native
OpenCode binary and let it own that one loopback OpenCode child. Disable native
OpenCode self-update through OpenChamber's supported policy, preserving unrelated
policy keys and rejecting a conflicting existing binary selection.
Leave `OPENCODE_PORT`, `OPENCODE_HOST` and `OPENCODE_SKIP_START` unset: this
release can adopt an existing server at an explicitly selected backend port.
Its managed backend should allocate its own loopback port. The explicit
OpenChamber web port fails on collision and is the only configured native port.

`qacey-dev` provides `sync [--source DIR] [--apply]`, `install-runtime [--apply]`,
`openchamber`, `codex PROJECT`, and `status`. `codex PROJECT` reuses the existing
project/Git-metadata boundary and attaches to a deterministic per-project tmux
session. A separate `qacey-codex-tmux.service` owns the tmux server so OpenChamber
PTY cleanup or a web restart does not kill Codex. Do not promise that running
processes survive a reboot. Codex's stored conversation can be resumed afterward.
One active harness owns edits in a worktree; concurrent tasks use separate
branches/worktrees. Handoff is a small repo-local note with goal, branch, relevant
files, completed validation and next steps, not copied transcript databases.

## HTTPS and authentication

Reuse the existing Oracle/WireGuard/home-Traefik HTTPS ingress. Keep SSH private.
Create a separate opt-in Compose project `qacey-dev-web`; the main platform's
`up --remove-orphans` must not manage it. Traefik routes only to OAuth2 Proxy.
OAuth2 Proxy routes over a private internal network to Caddy; Caddy proxies a
mounted Unix socket to a native `systemd-socket-proxyd` bridge and the loopback
OpenChamber listener. Neither the adapter nor native backend has a published
TCP port. The Unix socket is restricted to the dedicated account. Caddy runs as
that numeric UID/GID; OAuth2 Proxy runs as a separate unprivileged UID.

This extra small adapter is deliberate: pinned OAuth2 Proxy has separate Unix
HTTP and WebSocket transports, so direct Unix upstreams do not reliably carry
terminal WebSockets. Caddy handles HTTP, streaming and WebSockets on one Unix
upstream. Use image versions from `versions.env`: OAuth2 Proxy `v7.15.6` and
Caddy `2.11.9-alpine`. No Docker socket mounts or host-network containers.

Require an explicit public hostname, OIDC issuer/client, exact email allowlist,
and private secret files. No wildcard email-domain bypass, trusted-IP bypass or
unauthenticated application routes. Enforce MFA in the chosen identity provider;
SSO alone does not assert MFA. OAuth cookies use the `__Host-` prefix, Secure,
HttpOnly, Path `/`, no Domain and SameSite Lax. Use bounded expiry/refresh.
Do not forward IdP access tokens or replace OpenChamber's own Authorization
header. Preserve canonical Host and HTTPS forwarding; reject wrong-origin
browser requests and WebSocket handshakes.

OpenChamber additionally requires a strong UI password; passkeys may be enrolled
after activation. Do not set `OPENCODE_JWT_SECRET`, which changes its logout token
rotation behaviour. Secrets are root-owned mode0600 files edited through the
operator's terminal, never committed, generated into logs or supplied in chat.
Provisioning fails closed without complete activation configuration. Credential
placeholders are examples only, not functional defaults.

Stopping the web gateway cuts remote browser access. Cookie expiry/logout does
not necessarily terminate already-upgraded WebSockets; stopping the gateway is
the explicit revocation action. Stopping the separate tmux service also ends its
running Codex work. Avoid claiming that web logout cancels background jobs.

## Deployment and acceptance

The operator also requested Codex reviews for future pull requests, following
the official GitHub integration. Add a concise `Code Review Rules` section to
root `AGENTS.md`, and document repository plus personal automatic-review
settings at `https://chatgpt.com/settings/code-review`. Prefer this native
integration; it does not require an OpenAI API key in GitHub Actions. Enabling
the account-side toggle requires a signed-in Codex settings session and cannot
be asserted by committing repository files. Do not replace it with an API-billed
review workflow or claim it enabled until the setting is observed. Preserve
existing CI/branch protections; Codex review is an additional signal.

Qacey auto-deploy publishes reviewed baseline files. Applying user configuration,
upgrading native runtimes and restarting coding services are deliberate separate
steps. Root-installed configuration must not depend on a mutable live checkout.
Record the installed source version. Preserve the operator's stopped/disabled
intent during updates; provisioning never enables/restarts units.

Offline behaviour tests cover conflicts, repeat sync, correct schema mapping,
safe destination handling, identity, runtime verification and project/session
boundaries. CI validates rendered Compose/Caddy configuration and smoke-tests
pinned runtime packaging when network/runtime tooling is available. Real DNS,
TLS, IdP MFA/allowlist, mobile login, same-origin enforcement, WebSockets, reconnect,
private ports, reboot and backup/restore require host acceptance. Report those
as outstanding rather than claiming a live deployment.

## Primary references

- https://learn.chatgpt.com/docs/build-skills.md
- https://learn.chatgpt.com/docs/extend/mcp.md
- https://opencode.ai/docs/skills/
- https://opencode.ai/docs/mcp-servers/
- https://github.com/openchamber/openchamber/releases/tag/v2.8.0
- https://docs.openchamber.dev/reverse-proxy/
- https://docs.openchamber.dev/terminal/
- https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/
- https://github.com/oauth2-proxy/oauth2-proxy/blob/v7.15.6/pkg/upstream/http.go
- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
- https://www.freedesktop.org/software/systemd/man/latest/systemd-socket-proxyd.html
