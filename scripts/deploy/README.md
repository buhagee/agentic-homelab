# Deployment Scripts

Scripts for deploying configurations and services to production.

## Hermes Agent Deployment

### deploy-agent-config.sh
Deploys Hermes agent configuration, skills, and MCP servers.

**What it does:**
- Merges `config.shared.yaml` + per-user MCP JSON → `config.yaml`
- Deploys `SOUL.md` persona files
- Syncs skills (shared + per-user + wondelai community)
- Initializes mnemo-postgres database
- Deploys configured provider settings
- Loads `/.env` and overlays `/secrets/.env` when present for deploy-time secret substitution

**Usage:**
```bash
bash deploy/deploy-agent-config.sh [--force]
```

**Flags:**
- `--force` or `-f`: Overwrite custom skills from repo (default: preserve evolved skills)

**When to run:**
- After changing Hermes configuration
- After updating MCP server definitions
- After adding new skills
- After Hermes version upgrade

The shared `mcp_searxng` entry is an internal Streamable HTTP client for the
`mcp-searxng` Compose service. The service listens only on `qacey-internal` at
`http://mcp-searxng:3000/mcp`; it has no host port or Traefik route. Start or
update it through the normal platform Compose workflow after changing
`MCP_SEARXNG_IMAGE` in `versions.env`. The image must retain both a verified
release tag and immutable digest; never replace it with `latest`.

**Targets:**
- `hermes-justin` container
- `hermes-annique` container

**Skill deployment:**
- **Shared skills**: Always synced with `--ignore-existing` (SkillClaw can evolve)
- **Wondelai skills**: Always synced with `--ignore-existing` (450+ community skills)
- **Custom skills**: Only overwritten with `--force` flag

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
# 1. Update config files
nano services/agent/config.shared.yaml
nano services/agent/mcp-servers.shared.json

# 2. Deploy to agents
bash deploy/deploy-agent-config.sh

# 3. Restart agents
docker restart hermes-justin hermes-annique

# 4. Verify
docker logs -f hermes-justin
```

### SearXNG MCP rollback

To roll back this migration, restore the previous `mcp_searxng` stdio object
from Git, run `bash scripts/deploy/deploy-agent-config.sh`, and recreate both
Hermes containers. Remove or stop `mcp-searxng` separately if required. Do not
change the SearXNG image, settings, data, or JSON format during this rollback.

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

# Redeploy with force
bash deploy/deploy-agent-config.sh --force
```

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
