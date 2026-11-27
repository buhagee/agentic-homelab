# Global OpenChamber & OpenCode guidance

## Default response style (`caveman`)

Use the `caveman` skill for every response by default.

- Answer first, then reason, then next step.
- Remove greetings, ceremony, recaps, and closers.
- Keep code, commands, paths, API names, errors, numbers, units, and negations
  exactly as written.
- One idea per sentence. Clarity wins over compression.
- Stop caveman style when the user says "stop caveman" or "normal mode".

## Account layout: projects, skills, and MCPs

- **Projects (`~/projects`):** Active development repositories only. Read each
  repository's `AGENTS.md` before changing it. Keep one active writer per
  worktree; create separate branches/worktrees from a development clone for
  parallel work. Do not touch the operator's production checkouts.
- **Skill source checkouts (`~/.local/share/`):** Third-party skill repositories
  live under `~/.local/share/<name>` (not `~/projects`):
  - Superpowers (`v7.0.2`): `~/.local/share/superpowers`
  - Gstack (`v1.99.5.0`): `~/.local/share/gstack/src`
- **Discovered skills (`~/.agents/skills` and `~/.config/opencode/skills`):**
  - Account-wide portable skills: `~/.agents/skills` (`superpowers -> ~/.local/share/superpowers/skills`).
  - OpenCode/OpenChamber global skills: `~/.config/opencode/skills` (curated `gstack-*` lenses, `caveman`, `gh-fix-ci`).
  - Project-specific skills: `<repo>/.agents/skills`.
  - Before installing a skill, MCP server, or plugin, check these locations first
    and keep one owner per skill. Do not enable Gstack browser, shipping,
    deployment, or outside-review tools.
- **MCPs and plugins (`~/.config/opencode/opencode.json`):** Managed directly in
  this account or via the OpenChamber app, not through the Qacey platform repo.

## Server and Docker operations

- Use `qacey-dev-ops` for host and container diagnostics/actions:
  - `qacey-dev-ops list` — list allowed containers, systemd units, and flags.
  - `qacey-dev-ops monitor` — CPU, load, memory, and mount metrics.
  - `qacey-dev-ops storage` — disk usage, `/var/lib/docker` & `/var/lib/containerd` sizes, `docker system df`, and `docker container ls --all`.
  - `qacey-dev-ops status|logs|restart|start|stop containers <service>` — manage allowlisted Qacey containers.
  - `qacey-dev-ops status|logs units <unit>` — inspect allowlisted systemd units.
  - `qacey-dev-ops prune` — reclaim unused Docker images and build cache under the deploy lock.
- For root host operations not covered by a built-in `qacey-dev-ops` subcommand,
  run `qacey-dev-ops sudo -- <command...>` via `openchamber_secret` (`secret.run`)
  with environment variable `QACEY_SUDO_PASSWORD`. Never request passwords in
  plain-text chat or store tokens in source, logs, or handoffs.
