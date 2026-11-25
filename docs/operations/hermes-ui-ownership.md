# Hermes UI ownership contract

**Status:** active from 2026-11-25.

Hermes has one live writer per state. This document defines the boundary.

## Ownership

- **UI owns:** MCP servers, plugins, skills, OAuth tokens, model/provider
  settings, API keys, and the live `config.yaml`, `.env`, and `SOUL.md`.
- **Git owns:** base config seeds, images, networks, routes, personas, provider keys for non-Hermes services.
- **Deploy seeds. It never overwrites UI-owned state.**

| State | Owner | Location |
|---|---|---|
| Config seed | Git | `services/agent/config.shared.yaml` |
| Per-instance seed overlay | Git | `services/agent/config.<instance>.yaml` |
| Live config | UI | `/opt/data/config.yaml` |
| Live env / provider keys | UI | `/opt/data/.env` |
| Live persona | UI | `/opt/data/SOUL.md` |
| `mcp_servers` | UI | `/opt/data/config.yaml` |
| `plugins` | UI | `/opt/data/config.yaml` |
| Plugin files | UI | `/opt/data/plugins/` |
| Plugin dependency environments | UI | `/opt/data/installs/` |
| MCP OAuth tokens | UI | `/opt/data/mcp-tokens/` |
| Skills | UI | `/opt/data/skills/` |
| Tool HOME | UI | `/opt/data/home/` |
| Dashboard public URL | Git | Compose environment |

No live key is owned by both sides.

## Deploy behavior

`scripts/deploy/deploy-agent-config.sh`:

1. Ensures data, home, and skill directories exist.
2. Seeds `config.yaml` from `config.shared.yaml` + overlay **only when the live
   file is missing**.
3. Seeds `.env` from the platform environment **only when the live file is
   missing**.
4. Seeds `SOUL.md` from the Git persona **only when the live file is missing**.
5. Writes Google Workspace auth material from platform secrets.
6. Initializes the mnemo databases and deploys operational scripts.

Existing `config.yaml`, `.env`, and `SOUL.md` are never replaced.

Deploy still normalizes skill directory permissions and removes nested `.git`
metadata under the skill volumes. It does not change skill content.

That means the dashboard Config page owns:

- default model, provider, fallback
- vision and image generation
- security and approvals
- `mcp_servers`
- `plugins`
- `memory.provider` and `context.engine`

The dashboard API Keys page owns provider keys in `/opt/data/.env`.

## Seed files

The seed files are bootstrap-only:

```text
services/agent/config.shared.yaml
services/agent/config.justin.yaml
services/agent/config.annique.yaml
services/agent/persona.justin.md
services/agent/persona.annique.md
```

They matter on a fresh data volume. They are not applied to an existing
install. To reset live config from the seed, remove the live file deliberately
while the container is stopped, then run deploy.

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
    shared/          # shared skill library, read-only to the agent
    justin/          # per-agent library
  home/              # HOME for tools and MCP subprocesses
  workspace/         # default agent working directory
```

The agent container sets:

```text
HOME=/opt/data/home
HERMES_HOME=/opt/data
HERMES_WRITE_SAFE_ROOT=/opt/data
HERMES_WORKSPACE_DIR=/opt/data/workspace
```

`start.sh` runs `cd /opt/data/workspace` before starting the dashboard and
gateway. New chats therefore default to a previewable path.

Existing sessions keep their old working directory. If a chat still points at
`/opt/hermes`, start a new chat or select `/opt/data/workspace` in the workspace
picker. Files that already exist under `/opt/hermes` are application files, not
agent work; move user files to `/opt/data/workspace` or `/opt/data/sandbox`.

`HERMES_DASHBOARD_FILES_ROOT` stays unset. The managed root is then
`/opt/data`, and `~/.hermes`, skills, plugin state, and chat files are all
readable by the dashboard.

The image keeps a compatibility symlink:

```text
/opt/hermes/home/.hermes -> /opt/data/home
```

`start.sh` also links `$HOME/skills` to `/opt/data/skills` when that path is
free. Together they make file links from older chats resolve inside the managed
root. The links are read-only compatibility, not writable paths.

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
/opt/data/workspace               # default working directory
```

Before recreating the containers:

```bash
# Inspect what the old home contains.
find /mnt/ssd/qacey/hermes/justin/home -maxdepth 3 -type d | sort

# If old home held skills, move them into the shared skill tree.
# Do not leave a skills directory under the new HOME; Hermes won't scan it.
# mv /mnt/ssd/qacey/hermes/justin/home/skills/* \
#    /mnt/ssd/qacey/hermes/skills/justin/
```

The same host `justin/home` directory is reused. It is now mounted at
`/opt/data/home` instead of `/opt/hermes/home/.hermes`. Tool dotfiles such as
`.ssh`, `.gitconfig`, `.config`, and `.local` land in the correct place.

Existing `/opt/data/skills` content is preserved. The shared and per-agent skill
mounts appear as `/opt/data/skills/shared` and `/opt/data/skills/justin`.

Verify after recreate:

```bash
docker exec hermes-justin sh -lc \
  'printf "HOME=%s\nHERMES_HOME=%s\n" "$HOME" "$HERMES_HOME"; ls -ld /opt/data/home /opt/data/skills'
```

Then click a chat file again. It should preview without the managed-boundary
error.

## MCP policy

- Live MCP state is UI-owned.
- Manifests are archived under `docs/operations/hermes-mcp-reference/`. They
  are **reference only**. Deploy never reads them.
- Keep the archive only for migration and disaster-recovery reference.
- External and OAuth MCPs belong in the UI. Examples: Linear, Sentry, Notion,
  Atlassian, Figma.
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

Back up before the first seed-only deploy:

```bash
cp -p /mnt/ssd/qacey/hermes/justin/data/config.yaml \
  /mnt/ssd/qacey/hermes/justin/data/config.yaml.pre-ui-ownership
cp -p /mnt/ssd/qacey/hermes/justin/data/.env \
  /mnt/ssd/qacey/hermes/justin/data/.env.pre-ui-ownership
cp -p /mnt/ssd/qacey/hermes/justin/data/SOUL.md \
  /mnt/ssd/qacey/hermes/justin/data/SOUL.md.pre-ui-ownership
```

Then:

1. Deploy the seed-only version.
2. Verify existing MCPs, plugins, model, and keys are still present:
   `hermes mcp list`, `hermes plugins list`, `hermes config get model`.
3. Change the model or a key in the UI.
4. Deploy again.
5. Confirm the UI change survived.

Deploy must be a no-op for an initialized install.

## Rollback

There is no live `.pre-deploy` copy anymore. Use the manual pre-migration
backups above, or restore the latest `/opt/data` backup.

## Backup

Justin's offsite backup includes:

- `data/config.yaml`
- `data/.env`
- `data/SOUL.md`
- `data/plugins`
- `data/mcp-tokens`
- `data/skills`
- `data/workspace`
- `data/memories`
- `data/profiles`
- `data/google-workspace`
- `home/` (tool HOME: git/ssh/npm/uv and MCP credentials)

`data/installs` is not backed up by default. It is rebuildable and can be
large. Back up plugin source and tokens instead.

Annique's whole `data` directory is already in the backup set.

Backups are the recovery path now that Git no longer owns live config. Test a
restore before relying on it.
