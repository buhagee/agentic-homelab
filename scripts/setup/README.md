# Setup Scripts

Initial setup and configuration scripts for qacey-platform services.

## Server Setup

### isolate-agent-secrets.sh
Moves the platform `.env` and `secrets/.env` outside
the project directory and replaces them with symlinks.

**Usage:**
```bash
bash scripts/setup/isolate-agent-secrets.sh --dry-run
bash scripts/setup/isolate-agent-secrets.sh
```

**When to run:** On the host as `buhagiar` when migrating secrets out of the
project directory. See the backup restore notes for the secret path.

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

### Native development

See [Codex and OpenChamber](../../docs/operations/development.md) and
[optional operations access](../../docs/operations/dev-operations.md).

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

## Script Order

For a fresh setup, run in this order:

1. `server-setup-home.sh` (home server)
2. `server-setup-oracle.sh` (Oracle VPS)
3. `setup-wireguard-home.sh` (network tunnel)
4. `setup-oauth.sh` (Google OAuth)

## Notes

- All scripts are idempotent (safe to run multiple times)
- Scripts check prerequisites before running
- Most scripts require `.env` to be configured
- Scripts log to stdout (pipe to file if needed)
