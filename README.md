# agentic-homelab

A self-hosted platform for running AI agents, personal services, and the
infrastructure around them on a single home server plus a small VPS edge.

The platform is Docker Compose first. Everything is declared in git: service
definitions, Traefik routing, CrowdSec policy, backup and restore scripts, and
the OpenCode agent configuration. Secrets stay outside git and are rendered at
start time.

## Architecture

```
                     Internet
                        |
              +---------+----------+
              |   Oracle VPS       |
              |  Traefik (TLS)     |
              |  CrowdSec, uptime  |
              +---------+----------+
                        | WireGuard tunnel
              +---------+----------+
              |   Home server      |
              |  Traefik + services|
              |  OpenCode agents   |
              |  MCP tool servers  |
              |  Backups (restic)  |
              +--------------------+
```

- **Edge:** a small VPS terminates TLS, runs CrowdSec, and forwards traffic to
  the home server over WireGuard.
- **Core:** Docker Compose profiles run media, documents, passwords, home
  automation, search, and agent services.
- **Agents:** OpenCode runs in a container with a restricted controller for
  approved service actions. MCP servers provide search, academic, browser, and
  document tools.
- **Operations:** systemd timers run backups, health checks, deploy
  reconciliation, and Renovate. Git is the source of truth.

## Services

| Area | Examples |
| --- | --- |
| Edge and routing | Traefik, Cloudflared, CrowdSec |
| Agents | OpenCode, Hermes Web UI, MCP servers |
| Media and documents | Immich, Paperless-ngx, SearXNG, Crawl4AI |
| Personal | Vaultwarden, Home Assistant, AdGuard Home |
| Data | PostgreSQL with pgvector, Redis, Ollama |

## Quick start

```bash
cp .env.example .env
# fill in the values for your host
mkdir -p secrets
cp infrastructure/browser-oauth-allowed-emails.txt.example \
  secrets/browser-oauth-allowed-emails.txt
chmod 644 secrets/browser-oauth-allowed-emails.txt
bash scripts/setup/first-time-setup.sh
bash scripts/start.sh
```

Real secrets belong in `secrets/.env`. Traefik and OAuth templates are rendered
from `secrets/.env` at start time; rendered files are gitignored.

## Optional native Codex development

[Codex on the home server](docs/operations/codex.md) adds a dedicated development
account, independent project clones, a pinned runtime installer and an opt-in
remote-access unit. Start with the installer's dry-run; installation, sign-in and
activation are separate steps. Existing projects under the operator's home can be
live deployment checkouts and are not granted to the new account.

The current Compose services stay in place during this pilot. Merges to `main`
still trigger the existing deployment pipeline; Codex setup is never invoked by it.

## Security posture

- No credentials in git. Secret values live in `secrets/.env` on the host.
- CI runs gitleaks on every push and pull request.
- `main` requires a pull request and a green CI run. Direct pushes are blocked.
- Renovate automerges only stateless patch and minor image updates, after every
  required check passes.
- Containers drop capabilities, use read-only root filesystems where possible,
  and publish no host ports except the ones the edge needs.

## Licence

MIT. See [LICENSE](LICENSE).
