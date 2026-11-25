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

Renovate automerges patch and minor updates for both `stateless` and `stateful`
services. Major updates remain manual, except for the documented OpenCode
release rules. The `automerge-policy` job enforces that every Renovate PR only
changes `versions.env`.

Stateful patch/minor updates still may include migrations. The checks prove the
image exists and Compose resolves; they do not prove the service upgrades
cleanly. Keep backups current.

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
- Stateless `patch` and `minor`: labelled `stateless` and automerged.
- Stateful packages: labelled `stateful`. `patch` and `minor` automerge.
  Major updates are labelled `major` and stay manual. This includes Immich,
  Paperless, PostgreSQL, pgvector, Redis, Hermes, Vaultwarden, Home Assistant,
  CrowdSec, AdGuard, WireGuard and Ollama.
- Major updates: manual, labelled `major`, except the OpenCode release rules.
- OpenCode: patch automerges immediately; minor waits 2 days; major waits
  7 days.
- Security alerts are enabled and follow the same rules.

`HERMES_VERSION` and `MNEMO_PGVECTOR_VERSION` are deliberately not annotated:
the first is a Dockerfile build arg that the version PR cannot validate, and
the second is a major alias that needs a `pg_upgrade`. Bump both manually.

`OPENCODE_V2_VERSION` is tracked from the `anomalyco/opencode` GitHub v2
release line. Its Dockerfile fetches the matching `SHA256SUMS` asset, so a
version-only Renovate PR is buildable. The Node and pnpm pins remain manual.

A stateless PR should show the `stateless` label. A stateful patch/minor shows
`stateful` and automerges. A major PR shows `major` and stays manual, except the
OpenCode rules.

## Automerge path

1. Renovate opens a patch or minor PR touching only `versions.env`.
2. It adds the `stateless` or `stateful` label.
3. CI runs the required checks.
4. GitHub auto-merge merges when every check is green.
5. OpenCode minor and major use Renovate-side merging after their release-age
   delay.

The `automerge-policy` job fails any Renovate PR that changes files outside
`versions.env`.

## Major updates

Major updates of stateful services need a maintenance window and a fresh
database backup. The PR checks prove the image exists and the config resolves;
they do not prove the service migrates cleanly. Review the upstream release
notes, take a backup, then merge.

OpenCode majors are the documented exception: they automerge after 7 days.

## Verification

Before relying on the checks:

1. Open a draft PR that changes only a comment. Every required check should run
   on `ubuntu-latest` and pass.
2. Open a draft PR that points one image at a nonexistent tag. `images` must
   fail.
3. Open a draft PR that changes a file under a local build context.
   `build-changed` must build that service and no others.
4. Open a Renovate-style PR touching a stateless patch. Confirm the labels and
   auto-merge setting.
5. Open a Renovate-style PR touching a stateful patch. Confirm `automerge` is
   on. Open a stateful major PR and confirm `automerge` is off.

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
