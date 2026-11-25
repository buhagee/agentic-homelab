# Hermes UI ownership contract

**Status:** active from 2026-11-25.

Hermes has two writers only because each one owns a different state. This
document defines the boundary.

## Ownership

- **UI owns:** MCP servers, plugins, skills, OAuth tokens.
- **Git owns:** base config, images, networks, routes, personas, provider keys.
- **Deploy merges. It never overwrites UI-owned state.**

| State | Owner | Location |
|---|---|---|
| Base config | Git | `services/agent/config.shared.yaml` |
| Per-instance base overlay | Git | `services/agent/config.<instance>.yaml` |
| `mcp_servers` | UI | `/opt/data/config.yaml` |
| `plugins` | UI | `/opt/data/config.yaml` |
| Plugin files | UI | `/opt/data/plugins/` |
| Plugin dependency environments | UI | `/opt/data/installs/` |
| MCP OAuth tokens | UI | `/opt/data/mcp-tokens/` |
| Skills | UI | `/opt/data/skills/` |
| Tool HOME | UI | `/opt/data/home/` |
| Provider keys | Git secrets | `secrets/.env` |
| Integration API keys added by the UI | UI | `/opt/data/.env` |
| Dashboard public URL | Git | Compose environment |

No key is owned by both sides.

## Deploy behavior

`scripts/deploy/deploy-agent-config.sh`:

1. Renders the Git-owned base config and per-instance overlay.
2. Backs up the live config as `config.yaml.pre-deploy`.
3. Merges only `mcp_servers` and `plugins` from the live config.
4. Writes the result atomically with mode `600`.
5. Merges repo-managed keys into `.env`; UI keys and comments stay.
6. Backs up the live env as `.env.pre-deploy`.

The base config must not contain `mcp_servers` or `plugins`. Deploy fails
loudly if either key appears there.

Dashboard Config page edits to Git-owned keys are expected to be overwritten
on the next deploy. Use the UI for integration state, Git for everything else.

Provider-type plugin selections stored outside the `plugins` block
(`memory.provider`, `context.engine`) are Git-owned today. Add them to the base
config deliberately. General plugins, MCP servers, skills, and OAuth tokens do
not need a Git change.

## Runtime layout

Everything the dashboard may preview must live under `HERMES_HOME=/opt/data`.

```text
/opt/data
  config.yaml
  .env
  SOUL.md
  sessions/
  memories/
  plugins/
  mcp-tokens/
  skills/
    shared/          # SkillClaw shared library, read-only to the agent
    justin/          # per-agent library
  home/              # HOME for tools and MCP subprocesses
```

The agent container sets:

```text
HOME=/opt/data/home
HERMES_HOME=/opt/data
HERMES_WRITE_SAFE_ROOT=/opt/data
```

`HERMES_DASHBOARD_FILES_ROOT` stays unset. The managed root is then
`/opt/data`, and `~/.hermes`, skills, plugin state, and chat files are all
readable by the dashboard.

The image keeps a compatibility symlink:

```text
/opt/hermes/home/.hermes -> /opt/data/home
```

That makes file links from older chats resolve inside the managed root. The
symlink is read-only compatibility, not a writable path.

Do not point `HERMES_DASHBOARD_FILES_ROOT` at `/` or `/opt`. That exposes
`/opt/hermes`, the venv, and core source to the file API.

### Migrating from the old split layout

Old layout:

```text
/opt/data                         # Hermes state
/opt/hermes/home/.hermes          # HOME state, outside managed root
/opt/hermes/home/.hermes/skills   # skills, outside managed root
```

New layout:

```text
/opt/data                         # Hermes state
/opt/data/home                    # HOME state
/opt/data/skills                  # skills
```

Before recreating the containers:

```bash
# Inspect what the old home contains.
find /mnt/ssd/qacey/hermes/justin/home -maxdepth 3 -type d | sort

# If old home held skills, move them into the shared SkillClaw tree.
# Do not leave a skills directory under the new HOME; Hermes won't scan it.
# mv /mnt/ssd/qacey/hermes/justin/home/skills/* \
#    /mnt/ssd/qacey/hermes/skills/justin/
```

The same host `justin/home` directory is reused. It is now mounted at
`/opt/data/home` instead of `/opt/hermes/home/.hermes`. Tool dotfiles such as
`.ssh`, `.gitconfig`, `.config`, and `.local` land in the correct place.

Existing `/opt/data/skills` content is preserved. The SkillClaw mounts appear
as `/opt/data/skills/shared` and `/opt/data/skills/justin`.

Verify after recreate:

```bash
docker exec hermes-justin sh -lc \
  'printf "HOME=%s\nHERMES_HOME=%s\n" "$HOME" "$HERMES_HOME"; ls -ld /opt/data/home /opt/data/skills'
```

Then click a chat file again. It should preview without the managed-boundary
error.

## MCP policy

- Live MCP state is UI-owned.
- `services/agent/mcp-servers*.json` are **reference only**. Deploy never reads
  them.
- Keep a small Git seed list only for platform-internal MCPs whose URL and
  credentials are part of the platform: SearXNG, Crawl4AI, Paperless,
  academic-papers, Google Workspace. Use it to rebuild a host, not to drive
  every deploy.
- External and OAuth MCPs belong in the UI only. Examples: Linear, Sentry,
  Notion, Atlassian, Figma.
- The agent may propose an MCP. The agent must not silently add, enable, or
  replace one. A human approves it in the dashboard.
- Prefer remote HTTP MCP + OAuth over stdio. Set `auth: oauth` for OAuth
  servers.
- Test the connection, then restart the gateway.
- Use per-server tool filters and `trust: untrusted` for write-capable servers.

## Plugin policy

- Prefer catalog, official, or verified plugins.
- Pin full commits for anything you depend on.
- Plugins run in-process with full trust. Capabilities are consent, not a
  sandbox.
- Do not pip-install into `/opt/hermes/.venv`. Use `hermes plugins install` and
  `hermes plugins enable`.
- Enable only what you use.
- Keep auto-update off for Git plugins. Update deliberately.
- Plugins that need OS packages or host devices require an image rebuild. The
  UI cannot manage those.

## OAuth callback

Compose sets:

```text
HERMES_DASHBOARD_PUBLIC_URL=https://hermes.${QACEY_DOMAIN}
HERMES_DASHBOARD_PUBLIC_URL=https://hermes-annique.${QACEY_DOMAIN}
```

This pins the dashboard OAuth callback to the public hostname. Keep the
dashboard behind auth. Basic auth behind Cloudflare is acceptable; Cloudflare
Access or OIDC is better.

Providers without Dynamic Client Registration still pin a loopback callback.
For those, use `hermes mcp login <name>` over SSH with a port forward or pasted
redirect URL.

## Migration order

Back up before the first merge deploy:

```bash
cp -p /mnt/ssd/qacey/hermes/justin/data/config.yaml \
  /mnt/ssd/qacey/hermes/justin/data/config.yaml.pre-ui-ownership
cp -p /mnt/ssd/qacey/hermes/justin/data/.env \
  /mnt/ssd/qacey/hermes/justin/data/.env.pre-ui-ownership
```

Then:

1. Deploy the merge version.
2. Verify existing MCPs and plugins are still listed inside the container:
   `hermes mcp list` and `hermes plugins list`.
3. Re-add or repair MCPs in the UI.
4. Test each server, enable it, and restart the gateway.
5. Confirm a second deploy leaves the UI state unchanged.

Do not re-add every MCP at once. Add one, test, then add the next.

## Rollback

The deploy keeps one previous file per agent:

- `config.yaml.pre-deploy`
- `.env.pre-deploy`

To roll back a bad merge, stop the container, copy the `.pre-deploy` file back,
and start the container. Then revert the deploy change in Git.

## Backup

Justin's offsite backup includes:

- `data/config.yaml`
- `data/.env`
- `data/plugins`
- `data/mcp-tokens`
- `data/skills`
- `data/memories`
- `data/profiles`
- `data/google-workspace`
- `home/` (tool HOME: git/ssh/npm/uv and MCP credentials)

`data/installs` is not backed up by default. It is rebuildable and can be
large. Back up plugin source and tokens instead.

Annique's whole `data` directory is already in the backup set.

Test a restore before relying on it.
