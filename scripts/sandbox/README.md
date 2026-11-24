# Web sandbox

This is a host-managed, optional Streamlit runtime for web apps, dashboards,
reports, and simulations. It is disposable by default, but can run continuously
when its workspace, dependencies, and resource usage are managed deliberately.
It preserves the Hermes security boundary: Hermes can edit the workspace through
its existing `/opt/data` mount, but it cannot access Docker or restart arbitrary
host containers.

## Start

1. Add `SANDBOX_OAUTH2_COOKIE_SECRET` to [secrets/.env](../../secrets/.env).
   Generate it with `openssl rand -base64 32 | tr '+/' '-_' | tr -d '='`.
2. Register `https://sandbox.example.com/oauth2/callback` in the Google OAuth web client.
3. Edit [browser-oauth-allowed-emails.txt](../../secrets/browser-oauth-allowed-emails.txt)
   with one approved Google email per line.
4. Run `bash scripts/sandbox/start.sh` on the host.
5. Open `https://sandbox.example.com` and sign in with Google.

The route also works through the existing Cloudflare tunnel. Traefik applies
Google OAuth allowlisting and secure headers protect the route. No host port is published.

## Agent workflow

The agent edits `/opt/data/sandbox`, which maps to the sandbox workspace on the
host. The Home page is baked into the sandbox image and automatically
discovers Python pages mounted from `pages/`. Adding a new `pages/*.py` file
adds a new destination without Compose or Traefik changes. Changes to
`requirements.txt` are installed into tmpfs inside the sandbox, then the app
restarts.

The Home app is system-managed in the image and should not be changed by the
agent. Home changes require a repository/image rebuild by the host operator.
Agent-writable zones are `pages/`, `lib/`, `assets/`, `data/`, `artifacts/`,
and `requirements.txt`. Harden an existing workspace with:
`sudo bash scripts/sandbox/harden-workspace.sh`.

The recommended model is one Streamlit app with multiple pages. It keeps one
process, one port, one OAuth boundary, and one resource limit. It supports
dashboards, charts, image galleries, document previews/downloads, and small
interactive Python tools. Separate frameworks or independent long-running apps
would need a second sandbox service or a future process supervisor.

## Disposable versus long-lived

"Short-lived" describes the default operating model, not a runtime timeout.
The current sandbox has a persistent workspace and `restart: unless-stopped`,
but it remains an optional Compose profile and its app code/dependencies are
agent-managed. That is useful for experiments, but not a production contract.

For a long-lived app, promote it to its own service with:

- pinned image and dependency versions
- a reviewed or Git-backed workspace
- persistent artifact storage and backups
- dedicated resource limits and health alerts
- separate OAuth scope/allowlist when appropriate
- no automatic installation of arbitrary dependencies

Multiple pages are the low-cost path. Multiple independent apps should get
separate services only when they need different runtimes, failure isolation, or
independent release/backup policies.

To pause the app without Docker access, create `.disabled` in the workspace.
Remove `.disabled` to resume. To remove the container and route completely, run
`bash scripts/sandbox/stop.sh` on the host.

## Isolation

- Optional Compose profile: `sandbox`; not started by normal platform startup
- Dedicated `qacey-sandbox-edge` network shared only with Traefik
- Workspace mounted read-only inside runner
- No `/host` mount, Docker socket, published port, or platform-internal network
- Non-root UID, all capabilities dropped, `no-new-privileges`, read-only root FS
- 4 CPU cores, 4 GiB memory, and 512-process limit
- No sandbox credentials passed into the app container
- Home page and top-level control files are image/host-managed; page/content
   zones are writable by the agent

Treat generated code as untrusted. Keep sensitive data out of the sandbox
workspace. Approved OAuth users share access to the entire workspace/app.
