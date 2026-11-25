# Deployment Scripts

Scripts for deploying configurations and services to production.

## Hermes Agent Deployment

### deploy-agent-config.sh
Seeds Hermes config, env, and persona only when missing.

**Ownership:**
- **UI owns:** MCP servers, plugins, skills, OAuth tokens, model/provider, API keys, live config.
- **Git owns:** base config seeds, images, networks, routes, personas, provider keys for other services.
- **Deploy seeds. It never overwrites UI-owned state.**

See `docs/operations/hermes-ui-ownership.md` for the full contract.

**What it does:**
- Ensures data, home, and skill directories exist
- Seeds `/opt/data/config.yaml` only when missing
- Seeds `/opt/data/.env` only when missing
- Seeds `/opt/data/SOUL.md` only when missing
- Normalizes skill directory permissions; removes nested `.git` metadata
- Deploys Google Workspace auth material from platform secrets
- Initializes the mnemo-postgres database

Agent `HOME` is `/opt/data/home`. Skills are under `/opt/data/skills`. The
default working directory is `/opt/data/workspace`. All are inside the
dashboard managed root.

MCP manifests are archived under `docs/operations/hermes-mcp-reference/`.
They are **reference only**. Deploy never reads them. Add MCPs through the
Hermes dashboard at `https://hermes.${QACEY_DOMAIN}` or
`https://hermes-annique.${QACEY_DOMAIN}`.

**Usage:**
```bash
bash deploy/deploy-agent-config.sh
```

**When to run:**
- Initial host setup
- After changing the Git-owned seed for a fresh install
- After a Hermes version upgrade

Do not run it to change a live model, provider, key, MCP, or plugin. Use the
Hermes UI.

**Targets:**
- `hermes-justin` container
- `hermes-annique` container

**Skill and plugin state:**
- Managed through the Hermes UI.
- Plugin files and dependency environments live under `/opt/data`.
- Do not pip-install plugins into `/opt/hermes/.venv`.

The archived `mcp_searxng` entry is a reference for the internal Streamable HTTP
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
# 1. Change live agent config in the Hermes UI
#    model, provider, API keys, MCPs, plugins, skills
#    https://hermes.${QACEY_DOMAIN}
#    https://hermes-annique.${QACEY_DOMAIN}

# 2. Deploy only for infrastructure or a fresh seed
bash deploy/deploy-agent-config.sh

# 3. Restart agents when needed
docker restart hermes-justin hermes-annique

# 4. Verify UI state survived
docker exec hermes-justin /opt/hermes/.venv/bin/hermes mcp list
docker exec hermes-justin /opt/hermes/.venv/bin/hermes plugins list
docker exec hermes-justin /opt/hermes/.venv/bin/hermes config get model
```

### SearXNG MCP rollback

Roll back the `mcp_searxng` service through the normal Compose workflow. The
live Hermes MCP entry is UI-owned: if the service changes, update or disable the
entry in the Hermes dashboard. The archived manifest is reference only; editing
it does not change a deployment.

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
- **Non-destructive**: Never replaces an existing config, env, or persona
- **Rollback**: Restore the latest `/opt/data` backup
- **Logging**: All output logged to stdout

## Troubleshooting

### Hermes agent won't start after deploy
```bash
# Check config syntax
docker exec hermes-justin cat /opt/data/config.yaml

# Check logs
docker logs hermes-justin
```

Deploy does not keep a live `.pre-deploy` copy anymore. Restore the latest
`/opt/data` backup, or remove `config.yaml` while the container is stopped and
let the next deploy reseed it. Removing live config loses UI changes.

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
