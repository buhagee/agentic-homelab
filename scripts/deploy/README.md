# Deployment Scripts

Scripts for deploying configurations and services to production.

## Hermes Agent Deployment

### deploy-agent-config.sh
Deploys the Git-owned Hermes base config and merges live UI-owned state.

**Ownership:**
- **UI owns:** MCP servers, plugins, skills, OAuth tokens.
- **Git owns:** base config, images, networks, routes, personas, provider keys.
- **Deploy merges. It never overwrites UI-owned state.**

See `docs/operations/hermes-ui-ownership.md` for the full contract.

**What it does:**
- Renders `config.shared.yaml` + the per-instance overlay
- Preserves live `mcp_servers` and `plugins` blocks from `/opt/data/config.yaml`
- Writes `config.yaml.pre-deploy` before replacing the live config
- Merges repo-managed keys into `.env`; UI keys and comments stay
- Deploys `SOUL.md` persona files
- Initializes the mnemo-postgres database
- Loads `/.env` and overlays `/secrets/.env` when present

Agent `HOME` is `/opt/data/home`. Skills are under `/opt/data/skills`. Both
are inside the dashboard managed root.

`services/agent/mcp-servers*.json` are **reference only**. Deploy never reads
them. Re-add MCPs through the Hermes dashboard at
`https://hermes.${QACEY_DOMAIN}` or `https://hermes-annique.${QACEY_DOMAIN}`.

**Usage:**
```bash
bash deploy/deploy-agent-config.sh
```

**When to run:**
- After changing the Git-owned base config
- After changing provider keys
- After a Hermes version upgrade

Do not run it to add an MCP or plugin. Use the Hermes UI.

**Targets:**
- `hermes-justin` container
- `hermes-annique` container

**Skill and plugin state:**
- Managed through the Hermes UI.
- Plugin files and dependency environments live under `/opt/data`.
- Do not pip-install plugins into `/opt/hermes/.venv`.

The shared `mcp_searxng` entry is a reference for the internal Streamable HTTP
client for the `mcp-searxng` Compose service. The service listens only on
`qacey-internal` at `http://mcp-searxng:3000/mcp`; it has no host port or Traefik
route. The UI owns the live entry. Start or update the service through the
normal platform Compose workflow after changing `MCP_SEARXNG_IMAGE` in
`versions.env`. The image must retain both a verified release tag and immutable
digest; never replace it with `latest`.

## Oracle VPS Deployment

### oracle-deploy.sh
Deploys the Oracle VPS stack (monitoring + proxy).

**What it does:**
- Builds SkillClaw image (if needed)
- Pulls Docker images
- Starts containers:
  - `oracle-traefik` (TLS termination)
  - `uptime-kuma` (monitoring)
  - `wireguard-oracle` (tunnel server)
  - `crowdsec-oracle` (IDS)
  - `cs-traefik-bouncer-oracle` (bouncer)
- Registers CrowdSec bouncer
- Configures Traefik dynamic config

**Usage:**
```bash
# On Oracle VPS
bash deploy/oracle-deploy.sh
```

**Prerequisites:**
- `.env.oracle` configured
- WireGuard keys generated
- CrowdSec enrollment token (optional)

**When to run:**
- Initial Oracle VPS setup
- After configuration changes
- After updating Docker images

**Services deployed:**
- Traefik (ports 80, 443)
- Uptime Kuma (port 3001, internal)
- WireGuard (port 51820 UDP)
- CrowdSec (internal)

## Deployment Workflow

### Hermes Agent Updates
```bash
# 1. Update Git-owned base config or provider keys
nano services/agent/config.shared.yaml
nano .env

# 2. Add or change MCPs and plugins in the Hermes UI
#    https://hermes.${QACEY_DOMAIN}
#    https://hermes-annique.${QACEY_DOMAIN}

# 3. Deploy only when base config changed
bash deploy/deploy-agent-config.sh

# 4. Restart agents
docker restart hermes-justin hermes-annique

# 5. Verify UI state survived
docker exec hermes-justin /opt/hermes/.venv/bin/hermes mcp list
docker exec hermes-justin /opt/hermes/.venv/bin/hermes plugins list
```

### SearXNG MCP rollback

Roll back the `mcp_searxng` service through the normal Compose workflow. The
live Hermes MCP entry is UI-owned: if the service changes, update or disable the
entry in the Hermes dashboard. Do not edit `mcp-servers.shared.json` expecting
deploy to apply it; that file is reference only.

### Oracle VPS Updates
```bash
# 1. Update config
nano .env.oracle
nano infrastructure/traefik/oracle/traefik.yml

# 2. Deploy
bash deploy/oracle-deploy.sh

# 3. Verify
docker ps
curl -I https://status.example.com
```

## Safety

- **Idempotent**: Safe to run multiple times
- **Non-destructive**: Preserves existing data
- **Rollback**: Can revert by redeploying previous config
- **Logging**: All output logged to stdout

## Troubleshooting

### Hermes agent won't start after deploy
```bash
# Check config syntax
docker exec hermes-justin cat /opt/data/config.yaml

# Check logs
docker logs hermes-justin

# Restore the previous merged config if the new base is bad
cp -p /mnt/ssd/qacey/hermes/justin/data/config.yaml.pre-deploy \
  /mnt/ssd/qacey/hermes/justin/data/config.yaml
```

`config.yaml.pre-deploy` lives beside the live config in each agent's data
directory.

### Oracle VPS services not accessible
```bash
# Check containers
docker ps

# Check Traefik logs
docker logs oracle-traefik

# Check WireGuard tunnel
ping 10.100.0.2  # from Oracle
ping 10.100.0.1  # from home
```

## Notes

- Deploy scripts require `.env` (or `.env.oracle` for Oracle)
- Scripts are idempotent (safe to re-run)
- Always test in dev before deploying to prod
- Keep backups before major deployments
