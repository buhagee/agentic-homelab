# Deployment Scripts

Scripts for deploying configurations and services to production.

## Legacy agent retirement

The platform deploy checks the remaining stack before removing retired Compose
containers. It targets the old Docker OpenCode server and controller, both
Hermes agents and WebUI services, and the Hermes sandbox and its proxy. Matching
requires the `qacey-platform` project label and an exact retired service label.
Native Codex, OpenChamber's OpenCode runtime and the native development gateway
have separate lifecycles. Retirement also stops the Hermes-only Mnemo database
and its recurring database dumps. Container removal does not remove bind-mounted
state or volumes. Keep `/mnt/ssd/qacey/hermes`, `/mnt/ssd/qacey/postgres/mnemo`,
and any retained database exports until their data is no longer needed. Export any
legacy data you want to retain independently before the cutover. Existing offsite
snapshots age out under the standard retention policy.

### First home-server cutover

The installed runner and reconciliation timer execute the deployment script
from the current checkout. The old script still builds and provisions the
legacy agents. Use the new script for this cutover.

Before merging, let any active deployment finish and pause the home runner
and reconciliation timer from the operator terminal:

```sh
sudo systemctl stop actions.runner.buhagee-homeserver-deploy.homeserver.service
sudo systemctl stop qacey-deploy-reconcile.timer
```

After merging, confirm the operator checkout is clean and has its last-good
deployment marker. Fast-forward the checkout to load the new deploy and
database backup scripts, then deploy the merged revision:

```sh
cd ~/projects/qacey-platform
git status --short --branch
test -s "$HOME/.local/state/qacey-deploy/last-good"
git fetch origin main
git switch main
git merge --ff-only origin/main
bash scripts/deploy/auto-deploy.sh "$(git rev-parse HEAD)"
```

Resume the runner and timer after the deployment succeeds:

```sh
sudo systemctl start actions.runner.buhagee-homeserver-deploy.homeserver.service
sudo systemctl start qacey-deploy-reconcile.timer
```

After deployment, verify the removed service names are absent from
`docker ps -a --filter label=com.docker.compose.project=qacey-platform` in the
operator terminal. Disable stale external monitors or routes for the retired
hostnames if they were configured outside this repository.

## Oracle VPS Deployment

### oracle-deploy.sh
Deploys the Oracle VPS reverse proxy and security services.

**What it does:**
- Pulls Docker images
- Starts containers:
  - `oracle-traefik` (TLS termination)
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
- WireGuard (port 51820 UDP)
- CrowdSec (internal)

The first Oracle deploy after this change removes the retired Uptime Kuma
container and its HTTPS route. Its named data volume is retained. To silence
Kuma before the Oracle deploy, run `sudo docker stop uptime-kuma` on the Oracle
VPS. This stops all notifications sent by Kuma.

## Deployment Workflow

### Oracle VPS Updates
```bash
# 1. Update config
nano .env.oracle
nano infrastructure/traefik/oracle/traefik.yml

# 2. Deploy
bash deploy/oracle-deploy.sh

# 3. Verify
docker ps
curl -I https://vault.example.com
```

## Safety

- **Idempotent**: Safe to run multiple times
- **Non-destructive**: Never replaces an existing config, env, or persona
- **Rollback**: Restore the latest `/opt/data` backup
- **Logging**: All output logged to stdout

## Troubleshooting

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
