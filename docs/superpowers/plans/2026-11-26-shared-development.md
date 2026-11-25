# Shared Native Development Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenChamber and HTTPS access to the shared native development account, with portable configuration and safe switching between Codex and OpenCode.

**Architecture:** A versioned baseline renders into each client's configuration without replacing local settings. Native OpenChamber and a separate persistent Codex tmux service use the existing dedicated account; an opt-in authenticated web gateway connects to a private loopback backend.

**Tech Stack:** Python 3.11+ standard library, systemd, Node24, OpenCode2.4.1, OpenChamber2.8.0, tmux, Docker Compose, OAuth2 Proxy, Caddy, unittest.

**Spec:** [Shared development design](../../designs/2026-11-26-shared-development.md)

## Global Constraints

- Reuse the recorded dedicated account; do not hard-code a username/home in runtime configuration.
- All installers and sync default to dry-run and require `--apply`; no automatic login, deployment, enablement or restart.
- Keep Hermes and the existing Docker OpenCode installation unchanged; do not merge the PR.
- Independent development clones only, no production ownership changes, sudo/Docker/audio groups, credential copying or desktop installation.
- OpenCode `2.4.1`, OpenChamber `2.8.0`, Node >=24.14.0; verify official asset hashes before execution.
- Common guidance and portable skills/MCPs; client-specific permissions, models, plugins, auth and session stores.
- Preserve local additions, reject conflicting managed edits, and never print secret/config values in sync output.
- Web ingress uses the separate `qacey-dev-web` Compose project and only loopback/Unix native backends.
- Tests use temporary state and isolated processes; no live accounts, service activation or credentials.

## Review Focus

- Existing customised or symlinked config must not be overwritten; Task1 exercises migration and target conflicts.
- An interrupted sync must not destroy edits on retry; Task1 exercises recovery/partial state.
- A user-controlled path or unrelated binary must not be overwritten by an installer; Task2 exercises preflight and atomic publication.
- Terminal disconnects/web restarts must not own the Codex process lifetime; Task2 tests independent tmux invocation and documents host acceptance.
- A missing/wrong identity or public origin must not expose terminal traffic; Task3 tests fail-closed rendering and actual proxy configuration syntax.

## Task 1: Portable baseline and conflict-aware native configuration

**Files:**
- Create `infrastructure/dev-agent/shared/AGENTS.md`, `shared/mcp.json`, `sync_config.py` (split a pure MCP adapter module if useful).
- Create `scripts/setup/tests/test_dev_config.py`.

**Interfaces:**
- Consumes the existing foundation guidance at `infrastructure/codex/AGENTS.md.in` for safe initial migration; preserve edited copies.
- Produces `sync_config.sync(home: Path, source: Path, apply: bool = False) -> list[str]`, returning a redacted action summary; raises `ValueError`/`OSError` on conflicts.
- Produces `sync_config.managed_env_names(home: Path) -> set[str]`, reading only completed nonsecret state and refusing an unfinished sync; Task2 uses it to forward explicitly declared MCP variables.
- Source contains `AGENTS.md` and `mcp.json` schema1 with named `servers`; define and document the small common subset in the module and manifest.
- Native outputs are the two global guidance links, shared guidance, Codex's managed MCP block and OpenCode V2's managed MCP names; local state records previous owned values for safe repeat sync.
- Task2 installs these files and calls the API only after validating the current dedicated account.

- [x] Write failing behaviour tests for dry-run/no-op, both supported MCP transports and env refs, preserving unrelated plugins/models/MCPs, conflicting managed edits, removal of previously managed definitions, unknown fields/JSONC rejection, guidance migration, symlink collisions and interrupted/repeated application.
- [x] Implement the source validator, native adapters and narrow owned-state reconciliation using atomic file writes and an exclusive sync lock. Never replace the whole native configuration blindly.
- [x] Run `python3 -m unittest discover -s scripts/setup/tests -p 'test_dev_config.py' -v`; report the failing-before/passing-after evidence and the exact sync format.
- [x] Self-review, commit only Task1 files and write the implementation report for the scoped independent review.

## Task 2: Native runtimes, provisioning and persistent terminal sessions

**Files:**
- Create `infrastructure/dev-agent/qacey-dev`, `qacey-dev.py`, `install_runtime.py`, `release.json`, native service templates and helper modules only where needed.
- Create `scripts/setup/install-dev-agent.py` and `scripts/setup/tests/test_dev_runtime.py`, `test_dev_provision.py`, `test_dev_launcher.py`.
- May extend existing Codex helpers only to reuse their account/project validation safely; preserve current command behaviour.

**Interfaces:**
- Consumes Task1 `sync_config.sync`, source baseline and existing `codex_account.current_account()` / `qacey-codex.py:checked_project()`.
- Produces `python3 scripts/setup/install-dev-agent.py [--port 3939] [--apply]`, root-only for apply, using `/etc/qacey-codex/installation.json`.
- Produces `qacey-dev sync [--source DIR] [--apply]`, `install-runtime [--apply]`, `openchamber`, `codex PROJECT`, `status`.
- Installs root-owned helpers at `/usr/local/lib/qacey-dev`, launcher `/usr/local/bin/qacey-dev`, source snapshot and `/etc/qacey-dev/installation.json` with schema/version, account UID/GID/home and native port.
- Installs disabled `qacey-openchamber.service`, `qacey-codex-tmux.service`, `qacey-dev-proxy.socket` and `qacey-dev-proxy.service`. Unix proxy socket is `/run/qacey-dev-proxy/backend.sock`; dedicated tmux socket is `/run/qacey-codex-tmux/server.sock`.
- Task3 consumes the account record, socket path, native port and root-owned `/etc/qacey-dev` directory. Task2 does not create/start the Docker gateway or populate real secrets.

- [x] Write failing tests for dry-run/write boundaries, wrong account, unsafe pre-existing destinations and re-provisioning, verified runtime download/publication, traversal/symlink archive rejection, launch argv/environment, Git metadata boundary, and existing tmux reuse without spawning a second server.
- [x] Implement provisioning by reusing the existing account-record/trusted-path approach. Render correctly escaped units for nondefault homes. Install no account/groups and start no services. Use a private service environment file reference without fake working secrets.
- [x] Implement verified versioned nonroot runtime installation and rollback-friendly publication. Verify the actual upstream CLI/package interface; record any upstream install-script requirement. Ensure source/CI has enough runtime packaging information to reproduce installation.
- [x] Implement the launcher and separate tmux lifetime. Bind OpenChamber and its managed OpenCode child to loopback; use the pinned OpenCode policy without globally disabling user integrations.
- [x] Load allowed MCP environment references from the completed sync and optional private `mcp-env.json` in the actual Codex/OpenChamber child launcher, rejecting reserved harness/loader variables and unknown keys. Do not put values in argv. Leave backend OPENCODE_PORT/HOST/SKIP_START unset to avoid automatic adoption of an unrelated server.
- [x] Run the focused tests plus the existing Codex tests. Smoke-test runtime packaging/version/help in an isolated temporary directory if tooling/network permits; do not authenticate or activate services.
- [x] Self-review, commit only Task2 files and report evidence for scoped independent review.

## Task 3: Authenticated web gateway, operational integration and PR

**Files:**
- Create `infrastructure/dev-agent/web/compose.yml`, Caddy/OAuth templates and nonsecret example settings.
- Extend `scripts/setup/install-dev-agent.py` with explicit gateway rendering inputs, or add a focused `scripts/setup/install-dev-web.py` if it keeps provisioning readable.
- Create `scripts/setup/tests/test_dev_web.py` and isolated gateway/runtime validation script(s) under `scripts/testing`.
- Add Caddy pin to `versions.env`; extend existing CI jobs to validate opt-in Compose/config/runtime interfaces.
- Create `docs/operations/development.md`; update `README.md`, `AGENTS.md`, `docs/operations/codex.md` and `docs/operations/agent-tooling.md` navigation and boundaries.

**Interfaces:**
- Consumes Task2 record/socket/helpers, existing `qacey-proxy` Docker network and version registry.
- Produces an opt-in root-owned rendered gateway under `/etc/qacey-dev/web`, explicit public hostname/OIDC client/issuer/email allowlist inputs, private secret-file references, and documented manual activation/stop/update/rollback commands.
- Produces a complete switching workflow: shared projects/skills/MCP source, promotion of UI additions, separate plugin/auth/model settings, one-writer handoff and branch/worktree usage.

- [x] Write failing tests for hostname/issuer/email validation, no wildcard/bypass, missing secrets/activation settings, private networks/socket permissions, secure cookies, Authorization preservation, correct HTTPS/Host/Origin handling, and separate Compose project ownership.
- [x] Implement the minimal OAuth2Proxy→Caddy→Unix configuration, canonical-origin gate, secure service restrictions and root-only secret files. Render from root-owned installed assets so platform checkout resets do not mutate live configuration.
- [x] Validate actual Compose/OAuth/Caddy syntax and pinned native runtime version/help with isolated tooling/CI, recording unsupported local checks accurately. Extend existing CI without deployment side effects.
- [x] Document installation, sync, credentials, MFA, phone access, persistent Codex terminal, lifecycle/revocation, updates, backups/restore, host acceptance and deferred cleanup. Explain auto-deploy publishes the baseline while activation remains deliberate.
- [x] Add concise root `Code Review Rules` and native Codex GitHub review setup guidance. Enable repository/personal automatic-review settings if an authenticated account session is available; otherwise report the exact blocked account step. No API-key workflow is needed for this integration.
- [ ] Run `bash scripts/testing/run-all.sh`, `git diff --check`, relevant proxy/runtime smoke and existing secret/public hygiene checks. Resolve material independent review findings in one bounded final pass.
- [ ] Commit reviewed changes, update existing PR15 title/body, inspect CI and leave it unmerged. Report live activation and acceptance work as pending.
