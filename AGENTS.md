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

## Native Codex development

The optional native setup is documented in `docs/operations/codex.md`. Use its
dedicated account and independent development clones. The operator's existing
`~/projects` may contain live deployment checkouts: do not grant recursive write
access, change their ownership, or share their Git metadata with a coding worktree.
Ordinary edits, builds, tests and development networking within the dedicated
projects root are allowed within the authorized task. Use repository source/search
directly when an OpenCode-specific index or plugin is unavailable.

Privileged native-host changes are prepared for the operator to run in their own
sudo-authorized terminal. Never request a password in chat, copy the operator's
credential store, grant Docker membership, or run Codex as root. Setup and runtime
tests use temporary state; they do not create host accounts or activate services.

## Verification and operations

```sh
python3 -m unittest discover -s scripts/setup/tests -v
python3 -m unittest discover -s services/opencode-docker-control/tests -v
python3 -m unittest discover -s services/agent/google_workspace_mcp/tests -v
```

Run production smoke/deployment scripts only with explicit approval and the
required host environment. For the existing OpenCode stack, use the approved Docker controller for service
operations, with approval for every call. Do not mount a Docker socket into
OpenCode or bypass the controller's host-approved snapshot.
