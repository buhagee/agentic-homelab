# Shared development account

Use independent development clones under this account's `projects` directory.
Read each repository's `AGENTS.md` before changing it. The operator's existing
checkouts may run production services; do not change their ownership, share their
Git metadata, or treat them as development worktrees.

Codex and OpenCode share project files, this guidance and portable skills in
`~/.agents/skills` or repository `.agents/skills`. Keep model choices, permissions,
runtime plugins, login state and conversation history in each client's own
configuration. Promote portable MCP definitions to the versioned shared baseline
and apply them with `qacey-dev sync`; do not copy authentication stores.

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
are normal development work. For administrator operations, prepare the exact
command and purpose for the operator's own sudo terminal. Do not request passwords
in chat, run agents as root, grant Docker or privileged device groups, or copy the
operator's personal credentials. Keep tokens out of source, logs and handoffs.

For host diagnostics, use `qacey-dev-ops list` to discover the operator-approved
targets. `qacey-dev-ops status gateway adapter` reports the development gateway's
adapter status when granted. Check the gateway and the native units separately.

Qacey deployments publish the baseline. Applying configuration, upgrading native
runtimes and restarting coding services are separate deliberate operations.
