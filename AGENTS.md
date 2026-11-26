# Qacey platform agent guidance

This repository manages production infrastructure. Reading source and running
isolated tests is not permission to deploy, restart services, or read credentials.

## Choosing context tools

- **Global `open-codebase-index`, when available:** code discovery, semantic search, symbols and
  call relationships. Check `index_status` before relying on results. If it is
  stale or needs migration, request a normal refresh; never remove a live
  writer's lock or restart OpenCode to bypass it.
- Always verify the original cited source. An index hit is not proof of causal
  dependency; read the source before relying on a relationship.

## Shared native development

The optional Codex/OpenChamber setup is documented in `docs/operations/development.md`
and the underlying foundation in `docs/operations/codex.md`. Use their shared
dedicated account and independent development clones. The operator's existing
`~/projects` may contain live deployment checkouts: do not grant recursive write
access, change their ownership, or share their Git metadata with a coding worktree.
Ordinary edits, builds, tests and development networking within the dedicated
projects root are allowed within the authorized task. Use repository source/search
directly when an OpenCode-specific index or plugin is unavailable.

Privileged native-host changes use the operator's administrative terminal or the
explicitly enrolled `qacey-dev-deploy` path. Automatic deployment must use its
verified root-owned source, preserve stopped services and active coding work, and
keep native failures separate from platform rollback. The coding account receives
no sudo or Docker access. Never request a password in chat, copy the operator's
credential store, or run Codex as root. Setup and runtime tests use temporary
state; they do not create host accounts or activate services.

## Verification and operations

```sh
python3 -m unittest discover -s scripts/setup/tests -v
```

Run production smoke/deployment scripts only with explicit approval and the
required host environment. Where enrolled, use the allowlisted development
operations broker for approved service operations. Do not grant Docker socket
access to the development account.

## Documentation

Keep short-lived implementation plans, design drafts and review notes in the
ignored `.superpowers/` or `docs/superpowers/` directories; do not force-add them.
Commit durable setup and maintenance instructions, architecture decisions and
long-lived roadmaps. Remove completed task plans instead of retaining them as
operational documentation.

## Code Review Rules

- Identify production deployment, service restart and destructive side effects.
  Setup/tests must remain isolated or require explicit operator activation.
- Preserve account, authentication, network and secret boundaries. Reject root or
  Docker grants, public backend bypasses and credentials in source or logs.
- Preserve user configuration, credentials, data and stopped/disabled intent
  through upgrades and migrations. Require evidence for changed runtime interfaces.
