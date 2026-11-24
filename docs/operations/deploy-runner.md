# Self-Hosted Deploy Runner

This is the deployment path for `buhagee/qacey_platform`. Merges to `main`
dispatch to the private `buhagee/homeserver-deploy` repository, where a
self-hosted runner invokes the host deploy script.

The runner is deploy-only: it has no Docker group, no repository write access,
no `.env` or `secrets/.env` access, and sudo only to
`/usr/local/sbin/homeserver-deploy`.

## Flow

```
qacey_platform push to main
  -> .github/workflows/deploy-dispatch.yml
  -> repository_dispatch {app, sha}
  -> homeserver-deploy workflow
  -> self-hosted runner (github-runner)
  -> sudo /usr/local/sbin/homeserver-deploy app sha
  -> runuser -u buhagiar -- scripts/deploy/auto-deploy.sh sha
```

## 1. Create the deploy repository

The private repository already exists at
`https://github.com/buhagee/homeserver-deploy`. It contains only
`.github/workflows/deploy.yml`.

## 2. Install the runner

Generate a runner registration token from the deploy repository:

- GitHub → `buhagee/homeserver-deploy` → Settings → Actions → Runners →
  New self-hosted runner, or
- `gh api -X POST repos/buhagee/homeserver-deploy/actions/runners/registration-token --jq .token`

Then run as root on the homeserver:

```sh
cd /srv/agentic-homelab

sudo bash scripts/deploy/install-github-runner.sh \
  --url https://github.com/buhagee/homeserver-deploy \
  --token <registration-token>
```

The installer creates the `github-runner` user, downloads the pinned runner
`2.338.2`, verifies its SHA256, registers it with the `homeserver-deploy`
label, and installs/starts the systemd service.

## 3. Install the dispatcher

```sh
sudo bash scripts/deploy/install-deploy-dispatcher.sh
```

This installs:

- `/usr/local/sbin/homeserver-deploy` (root-owned, allowlist only)
- `/etc/sudoers.d/qacey-deploy`
- `/var/log/qacey-deploy.log` (owned by `buhagiar`)
- `/var/lock/qacey-deploy.lock`

Sudoers entries:

```text
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/homeserver-deploy
buhagiar ALL=(root) NOPASSWD: /usr/bin/systemctl start qacey-db-backup.service
```

## 4. Create the dispatch token

Create a fine-grained personal access token from a bot/machine account, scoped
only to `buhagee/homeserver-deploy`:

- Contents: read and write

Store it in `buhagee/qacey_platform` as the Actions secret
`DEPLOY_DISPATCH_TOKEN`. The app dispatch workflow skips when the secret is
missing, so merges are not noisy until it is configured.

## 5. Verify

Runner:

```sh
gh api repos/buhagee/homeserver-deploy/actions/runners \
  --jq '.runners[] | {name,status,busy,labels}'
```

Expected: one online, idle runner with the `homeserver-deploy` label.

Dry run:

```sh
cd /srv/agentic-homelab
bash scripts/deploy/auto-deploy.sh --dry-run "$(git rev-parse HEAD)"
```

Real dispatch:

```sh
gh workflow run deploy-dispatch.yml --ref main
```

Then:

```sh
gh run list --repo buhagee/homeserver-deploy --limit 3
sudo tail -100 /var/log/qacey-deploy.log
```

## Deploy behavior

The deploy script:

1. Refuses a dirty tracked working tree. Untracked `.env` and `secrets/.env`
   are preserved and never cleaned.
2. Verifies the SHA is on `origin/main` and is the current tip.
3. If the target SHA matches the last successfully deployed SHA recorded in
   `~/.local/state/qacey-deploy/last-good`, runs only a healthcheck and exits
   without pulling or recreating anything.
4. Dumps Immich, Paperless SQLite, and both Mnemo databases before changing
   images. The preflight accepts PostgreSQL (`.sql.gz`) or Paperless SQLite
   (`.sqlite3.gz`) dumps newer than two hours.
5. Builds changed local images.
6. Refreshes the Docker controller approval snapshot.
7. Pulls and updates the stack with `--wait`.
8. Runs the platform healthcheck.

The data-store images are digest-pinned in `versions.env`
(`IMMICH_POSTGRES_VERSION`, `MNEMO_PGVECTOR_VERSION`, `POSTGRES_VERSION`,
`REDIS_VERSION`), so `compose pull` cannot move them without a commit. Other
images are still tag-pinned; a real deploy may pull a moved tag.

Stateless failures roll back to the previous commit. Stateful failures leave
the containers in place, write a failed-SHA marker, and alert; restore the
database manually from `/mnt/hdd1/qacey/db-backups` if needed.

Rapid merges do not need one deploy per commit. The newest `main` tip contains
all earlier commits, so an older dispatch is skipped as `superseded`. The
host also runs `qacey-deploy-reconcile.timer` every 10 minutes; it fetches
`origin/main` and deploys the tip if it differs from `last-good`. That catches
dropped dispatches and GitHub outages.

Install the reconciliation timer:

```sh
sudo bash scripts/deploy/install-reconcile-timer.sh
systemctl list-timers qacey-deploy-reconcile.timer --no-pager
```

## Troubleshooting

- Runner offline: `systemctl status 'actions.runner.*' --no-pager`.
- Permission denied: confirm the sudoers file validates with
  `visudo -cf /etc/sudoers.d/qacey-deploy`.
- Dispatch skipped: `DEPLOY_DISPATCH_TOKEN` is missing or expired.
- Deploy refused: `git status --short` shows tracked changes, or the target
  SHA is not on `origin/main`.
- Failed SHA loop: fix forward with a new commit; the deploy script refuses the
  recorded failed SHA.
