# Qacey platform agent guidance

This repository manages production infrastructure. Reading source and running
isolated tests is not permission to deploy, restart services, or read credentials.

## Choosing context tools

- **Global `open-codebase-index`:** code discovery, semantic search, symbols and
  call relationships. Check `index_status` before relying on results. If it is
  stale or needs migration, request a normal refresh; never remove a live
  writer's lock or restart OpenCode to bypass it.
- Always verify the original cited source. An index hit is not proof of causal
  dependency; read the source before relying on a relationship.

## Verification and operations

```sh
python3 -m unittest discover -s scripts/setup/tests -v
python3 -m unittest discover -s services/opencode-docker-control/tests -v
python3 -m unittest discover -s services/agent/google_workspace_mcp/tests -v
```

Run production smoke/deployment scripts only with explicit approval and the
required host environment. Use the approved Docker controller for service
operations, with approval for every call. Do not mount a Docker socket into
OpenCode or bypass the controller's host-approved snapshot.
