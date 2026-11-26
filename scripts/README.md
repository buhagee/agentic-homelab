# Qacey Platform Scripts

Operational scripts for managing the qacey-platform infrastructure.

## Quick Start

```bash
# Start the platform
bash start.sh

# Stop the platform
bash stop.sh

# Reset (stop + clean volumes + start)
bash reset.sh

# Build custom images
bash build.sh

# Initial setup (first time only)
bash first-time-setup.sh
```

## Directory Structure

### Root Scripts (Frequently Used)
- **start.sh** — Start all platform services
- **stop.sh** — Stop all platform services
- **reset.sh** — Reset platform (stop, clean, restart)
- **build.sh** — Build custom Docker images
- **first-time-setup.sh** — Initial platform setup

### [setup/](setup/) — Initial Setup & Configuration
Server setup, OAuth configuration, service configuration.
- Server hardening (home + Oracle VPS)
- OAuth setup (Google)
- Service configuration (WireGuard)

### [deploy/](deploy/) — Deployment Scripts
Deploy configurations and services.
- Oracle VPS deployment

### [maintenance/](maintenance/) — Maintenance & Operations
Backup, cleanup, and operational maintenance.
- Backup scripts (local + offsite)
- Docker cleanup
- Service restarts
- User synchronization

### [testing/](testing/) — Testing & Verification
Smoke tests and API verification.
- Platform smoke tests
- API endpoint tests

### [tools/](tools/) — One-off Tools & Utilities
Standalone tools for specific tasks.
- Immich bulk upload (photos/videos from external drives)

## Usage Patterns

### Daily Operations
```bash
bash start.sh                    # Start platform
bash stop.sh                     # Stop platform
bash maintenance/backup.sh       # Run backup
```

### Setup & Configuration
```bash
bash first-time-setup.sh                    # Initial setup
bash setup/setup-oauth.sh                   # Configure OAuth
```

### Deployment
```bash
bash build.sh                               # Build images
bash deploy/oracle-deploy.sh                # Deploy to Oracle VPS
```

### Maintenance
```bash
bash maintenance/backup.sh                  # Run backup
bash maintenance/docker-cleanup.sh          # Clean Docker
```

### Testing
```bash
bash testing/smoke-test.sh                  # Run smoke tests
```

## Script Conventions

- **Executable**: All scripts are executable (`chmod +x`)
- **Bash**: All scripts use `#!/bin/bash`
- **Error handling**: Most scripts use `set -euo pipefail`
- **Logging**: Scripts log to stdout/stderr
- **Exit codes**: 0 = success, non-zero = failure

## Environment Variables

Most scripts source `.env` from the project root. See `.env.example` for required variables.

## Documentation

Each subdirectory has its own README with detailed information about the scripts it contains.

## Safety

- **Destructive operations** (reset, cleanup) prompt for confirmation
- **Production scripts** (deploy, backup) include safety checks
- **Secrets** are loaded from `.env` (never hardcoded)

## Support

For issues or questions:
1. Check the relevant subdirectory README
2. Review AIDLC documentation in `aidlc-docs/`
3. Check script comments for usage details
