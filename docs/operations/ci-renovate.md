# CI and Renovate Operations

This document covers the PR checks and version-update automation. The
self-hosted deploy runner is a separate change and is not enabled by this
workflow.

## Workflows

- `.github/workflows/ci.yml` runs on pull requests to `main` and manual
  dispatch. It runs on GitHub-hosted runners only.
- `.github/workflows/renovate.yml` runs daily at 18:00 UTC (04:00 AEST /
  05:00 AEDT) and on manual dispatch. It mints a GitHub App installation
  token and runs on GitHub-hosted runners only.
- Because GitHub's cron scheduler is unreliable on private repositories, the
  homeserver also runs `qacey-renovate.timer` at 18:15 UTC. It dispatches the
  same workflow and skips if a Renovate run started in the last two hours.
  Renovate still runs on GitHub-hosted infrastructure.

Install the timer:

```sh
sudo bash scripts/maintenance/install-renovate-timer.sh
systemctl list-timers qacey-renovate.timer --no-pager
```

## Required checks

`scripts/setup/github-main-ruleset.json` defines the `main-protection` ruleset
and is applied with:

```sh
bash scripts/setup/apply-github-ruleset.sh buhagee/agentic-homelab
```

Required status checks:

- `tests`
- `compose-config`
- `images`
- `renovate-config`
- `secrets`
- `automerge-policy`
- `opencode-smoke`

The ruleset also blocks direct pushes, force pushes, and branch deletion, and
requires conversation resolution. It has no bypass actors, so admins are bound
by it too.

## Merge policy

`main` requires a pull request and every check above. No approvals are
required: with a single maintainer GitHub cannot require self-approval, so the
gate is CI plus the no-direct-push rule.

Renovate automerges only PRs labelled `stateless` that touch `versions.env`.
The `automerge-policy` job enforces that. Unlabelled Renovate PRs for stateful
or major updates are manual: review and merge them yourself, or recreate the
change as a human-authored PR if you want the audit trail.

## Renovate identity

Renovate uses a GitHub App installed only on this repository. The workflow
mints a short-lived installation token with
`actions/create-github-app-token`; no personal access token is stored.

Create the GitHub App under the repository owner's account:

- **Homepage URL:** `https://github.com/buhagee/agentic-homelab`
- **Webhook:** inactive
- **Where it can be installed:** only this account
- **Name:** `qacey-renovate` (the bot author becomes `qacey-renovate[bot]`)

Repository permissions:

| Permission | Access |
| --- | --- |
| Contents | Read and write |
| Pull requests | Read and write |
| Issues | Read and write |
| Metadata | Read-only |
| Checks | Read-only |
| Commit statuses | Read-only |

Do not add Actions, Secrets, Administration, Members or Workflows write access.
If Renovate's `github-actions` manager is enabled later, Workflows read/write
becomes necessary because it edits files under `.github/workflows`.

Install the app on `qacey-platform`, generate a private key, and store:

- Repository variable `RENOVATE_APP_CLIENT_ID`: the App's Client ID.
- Repository secret `RENOVATE_APP_PRIVATE_KEY`: the full `.pem` contents,
  including the BEGIN and END lines.

The installation token expires automatically. Rotate the private key on a
schedule and immediately if it is exposed. Do not add the app as a
branch-protection bypass actor; it must still satisfy approvals and checks.

## Update policy

- Stateless whitelist: `traefik`, `cloudflare/cloudflared`, `searxng/searxng`,
  `unclecode/crawl4ai`, `ghcr.io/analogj/scrutiny`,
  `quay.io/oauth2-proxy/oauth2-proxy`.
- Stateless `patch` and `minor`: labelled `stateless`. Approve and merge
  manually after the checks pass. Auto-merge is not used on a private Free
  repository.
- Stateful packages: always manual, labelled `stateful`. This includes Immich,
  Paperless, PostgreSQL, pgvector, Redis, Hermes, Vaultwarden, Home Assistant,
  CrowdSec, AdGuard, WireGuard and Ollama.
- Major updates: always manual, labelled `major`.
- Security alerts are enabled and follow the same rules.

`HERMES_VERSION` and `MNEMO_PGVECTOR_VERSION` are deliberately not annotated:
the first is a Dockerfile build arg that the version PR cannot validate, and
the second is a major alias that needs a `pg_upgrade`. Bump both manually.

`OPENCODE_V2_VERSION` is tracked from the `anomalyco/opencode` GitHub v2
release line. Its Dockerfile fetches the matching `SHA256SUMS` asset, so a
version-only Renovate PR is buildable. The Node and pnpm pins remain manual.

A stateless PR should show the `stateless` label. A stateful PR should show
`stateful` and must be merged manually. A major PR should show `major` and must
be merged manually.

## Merging a stateless update

1. Confirm the PR only changes `versions.env` and the diff is the expected
   image.
2. Confirm `tests`, `compose-config`, `images`, `build-changed` and
   `renovate-config` are green.
3. Approve the PR and merge it manually.

There is no auto-merge on a private Free repository. If the account later moves
to Pro, re-enable `automerge` and `platformAutomerge` in `renovate.json` and
turn on `Allow auto-merge`.

## Stateful and major updates

These need a maintenance window and a fresh database backup. The PR checks
prove the image exists and the config resolves; they do not prove the service
migrates cleanly. Review the upstream release notes, take a backup, then merge.

## Verification

Before relying on the checks:

1. Open a draft PR that changes only a comment. All five checks should run on
   `ubuntu-latest` and pass.
2. Open a draft PR that points one image at a nonexistent tag. `images` must
   fail.
3. Open a draft PR that changes a file under a local build context.
   `build-changed` must build that service and no others.
4. Open a Renovate-style PR touching a stateless patch. Confirm the labels and
   auto-merge setting.
5. Open a Renovate-style PR touching a stateful version. Confirm `automerge`
   stays off.

## Troubleshooting

- `images` fails with a registry error: retry the job; the script retries three
  times but registry outages can outlast that.
- `compose-config` fails on a missing variable: the CI env comes from
  `.env.example`; add the variable there if it is required for config
  resolution.
- `build-changed` builds too much: inspect the service's `build.context` and
  the mapping script; contexts are matched by path prefix.
- Renovate opens no PRs: check the workflow run, the Client ID/private-key
  configuration, and the Dependency Dashboard issue.
