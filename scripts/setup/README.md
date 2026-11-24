# Setup Scripts

Initial setup and configuration scripts for qacey-platform services.

## Server Setup

### isolate-agent-secrets.sh
Moves the platform `.env` and `secrets/.env` outside
`/srv` and replaces them with symlinks, so the OpenCode
container cannot read them through `/workspace`.

**Usage:**
```bash
bash scripts/setup/isolate-agent-secrets.sh --dry-run
bash scripts/setup/isolate-agent-secrets.sh
```

**When to run:** After the tracked OpenCode config is deployed, on the host as
`buhagiar`. See the backup restore notes for the new secret path.

### server-setup-home.sh
Hardens the home server (Ubuntu 25.04).

**Features:**
- System updates and security patches
- UFW firewall configuration
- fail2ban installation
- sysctl hardening (rp_filter, syncookies, etc.)
- unattended-upgrades with auto-reboot
- CrowdSec sshd collection

**Usage:**
```bash
bash setup/server-setup-home.sh
```

**When to run:** Once during initial server setup, or after major OS changes.

### server-setup-oracle.sh
Hardens the Oracle VPS (Ubuntu 24.04).

**Features:**
- Same hardening as home server
- Oracle Cloud Agent disabled (frees RAM/CPU)
- UFW configured for WireGuard + Traefik

**Usage:**
```bash
bash setup/server-setup-oracle.sh
```

**When to run:** Once during Oracle VPS setup.

## OAuth & SSO Setup

### setup-oauth.sh
Configures Google OAuth for all platform services.

**Services configured:**
- Immich (photos)
- Vaultwarden (vault)

**Usage:**
```bash
bash setup/setup-oauth.sh
```

**Prerequisites:**
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`
- Services must be running

**When to run:** After first-time-setup, or when OAuth settings change.

## Service Configuration

### OpenCode V2 remote app
OpenCode V2 is served at `https://opencode.example.com` through Traefik TLS and
requires the generated `OPENCODE_PASSWORD` from `secrets/.env`. Connect the
OpenCode app to that server URL using the password. The server mounts
`/srv` at `/workspace`, so each project folder is available
at the same relative path inside the container. Its persistent state is stored
on the SSD at `/mnt/ssd/qacey/hermes/opencode-v2`.
The shared OpenCode server is connected to the platform's Crawl4AI and SearXNG
MCPs over a dedicated internal Docker network; both are configured globally.
`open-codebase-index` is also configured globally. Superpowers loads only
in projects that register its pinned plugin. The code index uses the local
Ollama `nomic-embed-text` model and the seven repositories
under `/srv`; indexing is on demand with `/index`, and the
global index is stored with OpenCode's persistent state.
The OpenCode image uses a digest-pinned Debian glibc base because the indexer's
native module requires glibc 2.43; its binary checksum is pinned in
`versions.env` alongside the OpenCode version.

OpenCode runs as UID 1000 without `sudo` or a Docker socket. Docker service
operations are exposed through a separate internal controller and require
OpenCode approval for each tool call. It supports status, logs, start, stop,
restart, build, and single-service `up`; build/recreate is excluded for
privileged, host-network, capability-adding, device, and Docker-socket services.
The controller rejects operations if the Compose file, versions file, or
environment files differ from the host-approved snapshot. After reviewing
changes to those files, refresh the snapshot from the host terminal:

```bash
python3 scripts/setup/install-opencode-docker-control.py
```

The controller's Docker socket is not mounted into OpenCode. Docker access is
still a sensitive host capability, so keep the controller on its internal
network and approve service operations deliberately.

To start the shared server's terminal UI over SSH from any directory under
`/srv`, run `scripts/opencode.sh` (or `oc` after adding the
alias below to `~/.bashrc`):

```bash
alias oc='/srv/agentic-homelab/scripts/opencode.sh'
```

The script maps the current host directory into the container workspace and
connects to the same OpenCode server used by the app.

### setup-gstack-lenses.sh

Restores the owner-approved gstack lenses to the shared persistent home.
Projects opt in by adding `~/.local/share/gstack/home/.config/opencode/skills`
to their `opencode.json` and keeping approved `/gstack-*` commands in their
own `.opencode/commands/`. The install does not register a global skill source
or global commands. Browser, shipping, deployment, upgrade, and outside-review
lenses stay disabled.

```bash
bash scripts/setup/setup-gstack-lenses.sh
```

The script pins gstack 1.99.5.0 and Bun 1.4.2, verifies the Bun checksum,
applies the privacy settings, and records the hand patch for `qa-only`'s
section link. It writes only to `~/.local/share/gstack` and `~/.gstack`; it does
not restart OpenCode or change tracked files. `setup --status` must report all
section links resolving.

### install-hacs.sh

Manual, optional Home Assistant utility that installs HACS into the Home
Assistant container. Run only when HACS is wanted:

```bash
bash scripts/setup/install-hacs.sh
```

### Hermes direct dashboard (Hermex 2.0)
Hermex 2.0 (iOS) can connect directly to each Hermes Agent's own built-in
dashboard instead of the separate `hermes-webui` container — required for
"Move to Hermes" and session-edit features, available on Hermes >= 0.22.3.
Each agent's dashboard is served at `https://hermes.example.com` (Justin) and
`https://hermes-annique.example.com` (Annique) through Traefik TLS, with
sign-in credentials from `secrets/.env`
(`HERMES_DASHBOARD_USERNAME_JUSTIN`/`_PASSWORD_JUSTIN` and the `_ANNIQUE`
equivalents). Justin's `hermes-webui-justin` was retired after confirming the
direct dashboard worked; `hermes-webui-annique` keeps running in parallel —
sign in with its own URL/password as before, or use **Move to Hermes** in the
app to migrate. Platform alerts (backup, CrowdSec and the host healthcheck) use
Google Workspace email; Hermes has no host filesystem or server-monitoring
access.

**Usage:**
```bash
```


## Network Setup

### setup-wireguard-home.sh
Configures WireGuard client on home server.

**Features:**
- Generates WireGuard config from `.env` keys
- Writes to `/etc/wireguard/wg0.conf`
- Configures tunnel to Oracle VPS

**Usage:**
```bash
bash setup/setup-wireguard-home.sh
```

**Prerequisites:**
- `WIREGUARD_HOME_PRIVATE_KEY` in `.env`
- `WIREGUARD_ORACLE_PUBLIC_KEY` in `.env`

**When to run:** During U-11 (self-hosted proxy setup).

## Monitoring Setup

### setup-uptime-kuma.sh
Configures Uptime Kuma monitoring.

**Features:**
- Creates monitors for all services
- Prints the manual SMTP notification configuration for the Uptime Kuma UI
- Sets up status page

**Usage:**
```bash
bash setup/setup-uptime-kuma.sh
```

**Prerequisites:**
- Uptime Kuma running on Oracle VPS
- SMTP values available for the manual notification step

**When to run:** After Uptime Kuma is deployed (U-09).

## Script Order

For a fresh setup, run in this order:

1. `server-setup-home.sh` (home server)
2. `server-setup-oracle.sh` (Oracle VPS)
3. `setup-wireguard-home.sh` (network tunnel)
4. `setup-oauth.sh` (Google OAuth)
5. `setup-uptime-kuma.sh` (monitoring)

## Notes

- All scripts are idempotent (safe to run multiple times)
- Scripts check prerequisites before running
- Most scripts require `.env` to be configured
- Scripts log to stdout (pipe to file if needed)
