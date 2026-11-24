# OpenCode global config

This directory is the source of truth for `opencode-v2`'s global OpenCode
configuration. It is bind-mounted read-only into the container at
`/home/opencode/.config/opencode`.

- `opencode.json`: plugins, model pins, permissions, and MCP servers.
- `codebase-index.json`: code-index scope and embedding settings.
- `instructions/`, `model-pins/`, `skills/`: curated global agent assets.
- `commands/` has no global workflow commands; keep it for the read-only mount.
- `service.json`, auth, sessions, and the OpenCode database remain on the
  persistent SSD and are not tracked.

See [the tooling pick](../../../docs/operations/agent-tooling.md) for the
current global and project-local choices.

The `academic-papers` MCP is available because `mcp-academic-papers` joins the
internal `qacey-opencode-mcp` network.

Credentials are never stored here. Use `opencode auth login` inside the
container, or the supported provider connection flow.

Superpowers and Gstack workflows are not registered globally. Qacey Platform
pins Superpowers in its project-root `opencode.json`. Projects using the
owner-approved Gstack lenses may add
`~/.local/share/gstack/home/.config/opencode/skills` to their project config and
keep their own `.opencode/commands/` entries. The shared Gstack install can be
recreated with `scripts/setup/setup-gstack-lenses.sh`; installing it does not
register it globally. The global skill deny rules still apply.
