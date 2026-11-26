# Shared development account

Use independent development clones under this account's `projects` directory.
Read each repository's `AGENTS.md` before changing it. The operator's existing
checkouts may run production services; do not change their ownership, share their
Git metadata, or treat them as development worktrees.

Codex and OpenCode share project files, this guidance and portable skills in
`~/.agents/skills` or repository `.agents/skills`. Keep model choices, permissions,
runtime plugins, login state and conversation history in each client's own
configuration. Do not copy authentication stores.

Before installing a skill, MCP server, or plugin, check the shared locations,
the repository's configuration, and the relevant client's configuration for an
existing installation. Reuse the existing pinned version and keep one owner per
skill. When reporting an installation, include its version or revision, location,
and the clients or repositories it serves.

- Put account-wide portable skills in `~/.agents/skills` and project-specific
  portable skills in the repository's `.agents/skills`. An existing reviewed
  source checkout can be linked from the appropriate skills directory.
- Put MCP definitions intended for both clients in Qacey's versioned
  `infrastructure/dev-agent/shared/mcp.json`. Preview with `qacey-dev sync` and
  apply with `qacey-dev sync --apply` after the updated baseline is published.
- Install client-specific plugins and hooks through that client's native
  configuration. Use the project's package manager for project dependencies
  and the operator's administrative terminal for system packages.

Keep one active writer per worktree. For simultaneous tasks, create separate
branches/worktrees from a development clone. When switching harnesses, leave a
short handoff with the goal, branch, relevant files, validation completed and next
steps. Read the actual changes and test results before continuing.

Follow the owner's selected Superpowers workflow and curated Gstack lenses.
Keep one installation owner per skill; host-specific plugins are installed for
their own harness. Do not enable Gstack browser, shipping, deployment or
outside-review tools. Use project-local Playwright CLI/skills for headless browser
work when required; this server has no graphical desktop.

Edits, builds, tests and development networking within the authorised workspace
are normal development work. For administrator operations, use `qacey-dev-ops`
(including `qacey-dev-ops sudo -- <cmd>` authenticated via OpenChamber's private
`openchamber_secret` card when enabled in `/etc/qacey-dev-ops/policy.json`) or
prepare the exact command and purpose for the operator's own sudo terminal. Do
not request passwords in plain-text chat, run agents as root, grant Docker or
privileged device groups, or copy the operator's personal credentials. Keep
tokens out of source, logs and handoffs.

For host diagnostics and ops, use `qacey-dev-ops list`, `qacey-dev-ops monitor`,
`qacey-dev-ops storage`, and `qacey-dev-ops prune` as enabled by policy.
`qacey-dev-ops status gateway adapter` reports the development gateway's
adapter status when granted. Check the gateway and the native units separately.

Qacey deployments publish the baseline. Applying configuration, upgrading native
runtimes and restarting coding services are separate deliberate operations.
