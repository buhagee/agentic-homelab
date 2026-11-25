# Hermes UI Ownership Separation Implementation Plan

> **Superseded 2026-11-25:** this plan implemented merge-preserving deploy.
> The final design is seed-only: deploy writes `config.yaml`, `.env`, and
> `SOUL.md` only when missing. The merge helper and its tests were removed.
> Keep this document for history; use `docs/operations/hermes-ui-ownership.md`
> as the active contract.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the Hermes web UI the single writer for MCP servers, plugins, skills, and OAuth tokens while Git remains the single writer for base infrastructure and provider configuration.

**Architecture:** `deploy-agent-config.sh` renders the Git-owned base config, then merges the live UI-owned `mcp_servers` and `plugins` blocks from the existing `config.yaml`. It merges `.env` by updating only repo-managed keys. A stdlib-only Python helper performs both merges atomically. MCP JSON manifests remain reference seeds only and are never applied automatically.

**Tech Stack:** Bash, Python 3 standard library, Docker Compose YAML, `unittest`.

**Spec:** User ownership contract agreed 2026-11-25: UI owns integrations; Git owns infrastructure; deploy merges and never overwrites UI-owned state.

## Global Constraints

- Do not deploy, restart, or mutate production containers in this plan.
- `mcp_servers` and `plugins` are UI-owned top-level `config.yaml` keys.
- Skills and OAuth tokens are UI-owned volume state, not deploy artifacts.
- Git-owned base config must not define `mcp_servers` or `plugins`.
- Python helper uses only the standard library; no PyYAML or yq.
- Writes are atomic and mode `600`.
- Existing MCP JSON files stay as migration reference only.
- `.env` keys not listed as repo-managed are preserved exactly.
- No secret values in process arguments or logs.

## Review Focus

- Existing live config missing: first deploy writes base config only.
- Base config defines a UI-owned key: deploy fails loudly instead of duplicating YAML.
- UI `.env` contains comments or unrelated keys: merge preserves them.
- Managed `.env` value is empty: stale value is removed.
- Managed `.env` value contains spaces, `#`, quotes, or `$`: written verbatim.
- Live config has one UI block only or duplicate blocks: handle deterministically.
- Merge failure leaves the previous config intact.
- File mode stays `600` after merge.
- MCP JSON reference files are not read by deploy.
- Justin and Annique both use the same merge path.

---

### Task 1: Add the stdlib merge helper

**Files:**
- Create: `scripts/lib/hermes_state_merge.py`
- Test: `scripts/setup/tests/test_hermes_state_merge.py`

**Interfaces:**
- Produces:
  - `merge_config(base_text: str, live_text: str, preserve_keys: Sequence[str] = ("mcp_servers", "plugins")) -> str`
  - `merge_env(existing_text: str, managed: Mapping[str, str]) -> str`
  - CLI: `python3 scripts/lib/hermes_state_merge.py config --base PATH --live PATH --output PATH`
  - CLI: `python3 scripts/lib/hermes_state_merge.py env --existing PATH --output PATH --managed-key KEY [--managed-key KEY ...]`

- [x] **Step 1: Write the failing helper tests**

Create `scripts/setup/tests/test_hermes_state_merge.py` with tests for:

```python
def test_config_preserves_mcp_and_plugins_blocks():
    base = "model:\n  provider: opencode-go\n"
    live = (
        "model:\n  provider: old\n"
        "mcp_servers:\n  searxng:\n    url: http://mcp-searxng:3000/mcp\n"
        "plugins:\n  enabled:\n    - mcp-serve\n"
    )
    result = merge_config(base, live)
    assert "mcp_servers:" in result
    assert "plugins:" in result
    assert "provider: opencode-go" in result
    assert "provider: old" not in result
```

Also test: first deploy with no live config; base collision raises `ValueError`; duplicate live block raises `ValueError`; trailing comments and nested lines survive; `.env` updates managed keys while preserving UI keys and comments; empty managed value removes stale key; newline in value raises; atomic write sets mode `600`.

- [x] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_hermes_state_merge.py' -v`
Expected: FAIL with `ModuleNotFoundError` or missing `merge_config`.

- [x] **Step 3: Implement the helper**

Use top-level YAML block detection with `^([A-Za-z0-9_.-]+):(?:\s|$)`; do not parse YAML semantics. Extract the whole block through the line before the next top-level key. Preserve text verbatim. Reject duplicate preserved keys and any preserved key already present in the base. Write with `tempfile.NamedTemporaryFile` in the destination directory, `os.fsync`, `chmod(0o600)`, then `os.replace`.

For `.env`, match `^([A-Za-z_][A-Za-z0-9_]*)=`; drop managed keys, preserve all other lines, append managed keys in argument order. Reject keys outside the regex and values containing `\n` or `\r`.

- [x] **Step 4: Run tests and verify pass**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_hermes_state_merge.py' -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/lib/hermes_state_merge.py scripts/setup/tests/test_hermes_state_merge.py
git commit -m "feat: add Hermes config and env merge helper"
```

---

### Task 2: Preserve UI config during deploy

**Files:**
- Modify: `scripts/deploy/deploy-agent-config.sh`
- Test: `scripts/setup/tests/test_searxng_mcp_contract.py`
- Test: `scripts/setup/tests/test_cleanup_contract.py`

**Interfaces:**
- Consumes: `scripts/lib/hermes_state_merge.py config`.
- Produces: `write_config_yaml <dest>` preserving live `mcp_servers` and `plugins`.

- [x] **Step 1: Write the failing contract tests**

Replace the old renderer test with assertions that `deploy-agent-config.sh`:
- calls `hermes_state_merge.py config`
- does not pass `mcp-servers.shared.json` to `write_config_yaml`
- still calls `write_config_yaml` for Justin and Annique
- writes a `.pre-deploy` backup and chmods the result `600`

- [x] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_searxng_mcp_contract.py' -v`
Expected: FAIL on missing merge-helper usage and old manifest references.

- [x] **Step 3: Implement config preservation**

Update `write_config_yaml` to:
- render `config.shared.yaml` plus the per-instance overlay with `envsubst`
- validate unresolved vars on the rendered base only
- copy the live config to `config.yaml.pre-deploy` when present
- invoke the merge helper to preserve `mcp_servers` and `plugins`
- chmod `600` and remove temp files

Remove the MCP JSON merge, `jq` validation, and Google Workspace MCP deletion. Keep `assert_no_embedded_secrets` on the merged file. Add a warning when a `google_workspace` MCP remains configured but its auth file is absent.

- [x] **Step 4: Run tests and verify pass**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_searxng_mcp_contract.py' -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/deploy/deploy-agent-config.sh scripts/setup/tests/test_searxng_mcp_contract.py
git commit -m "feat: preserve UI-owned Hermes config during deploy"
```

---

### Task 3: Merge runtime `.env` instead of truncating it

**Files:**
- Modify: `scripts/deploy/deploy-agent-config.sh`
- Test: `scripts/setup/tests/test_agent_media_provider_contract.py`

**Interfaces:**
- Consumes: `scripts/lib/hermes_state_merge.py env`.
- Produces: `write_runtime_env <dest>` that updates repo-managed keys and preserves all others.

- [x] **Step 1: Write the failing contract test**

Update `test_runtime_env_carries_generation_settings_without_logging_secrets` to assert the deploy script calls `hermes_state_merge.py env` with `--managed-key` entries for each repo-managed key, including `HERMES_IMAGE_GEN_MODEL` and `OPENCODE_GO_BASE_URL`, and calls `write_runtime_env` for both agents.

- [x] **Step 2: Run test and verify failure**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_agent_media_provider_contract.py' -v`
Expected: FAIL because deploy still rewrites `.env` with heredocs.

- [x] **Step 3: Implement `.env` merge**

Replace both heredocs with one `write_runtime_env` function. Pass only key names to the helper; values come from the exported deploy environment. Preserve UI-added keys. Keep `chmod 600`.

- [x] **Step 4: Run test and verify pass**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_agent_media_provider_contract.py' -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/deploy/deploy-agent-config.sh scripts/setup/tests/test_agent_media_provider_contract.py
git commit -m "feat: merge Hermes runtime env keys"
```

---

### Task 4: Add OAuth callback URL and backup coverage

**Files:**
- Modify: `docker-compose.platform.yml`
- Modify: `scripts/maintenance/backup.sh`
- Test: `scripts/setup/tests/test_backup_contract.py`

**Interfaces:**
- Produces: `HERMES_DASHBOARD_PUBLIC_URL` for both agents; Justin backup paths for `plugins` and `mcp-tokens`.

- [x] **Step 1: Write failing assertions**

Add tests that both Hermes services set `HERMES_DASHBOARD_PUBLIC_URL` to their exact public hostname, and that backup includes:
- `/mnt/ssd/qacey/hermes/justin/data/plugins`
- `/mnt/ssd/qacey/hermes/justin/data/mcp-tokens`

- [x] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_backup_contract.py' -v`
Expected: FAIL on missing paths and env var.

- [x] **Step 3: Implement**

Add:
```yaml
HERMES_DASHBOARD_PUBLIC_URL: "https://hermes.${QACEY_DOMAIN}"
```
and the Annique equivalent. Add the two backup paths with `add_restic_path`.

- [x] **Step 4: Run tests and verify pass**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_backup_contract.py' -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add docker-compose.platform.yml scripts/maintenance/backup.sh scripts/setup/tests/test_backup_contract.py
git commit -m "feat: configure Hermes OAuth callback and UI-state backup"
```

---

### Task 5: Document the ownership contract and migration

**Files:**
- Create: `docs/operations/hermes-ui-ownership.md`
- Modify: `scripts/deploy/README.md`
- Modify: `services/agent/config.shared.yaml`
- Modify: `secrets/README.md`
- Modify: `.env.example`
- Test: `scripts/setup/tests/test_hermes_ui_ownership_contract.py`

**Interfaces:**
- Produces: operational contract explaining UI-owned state, Git-owned state, migration order, rollback, backup, and MCP seed policy.

- [x] **Step 1: Write the failing doc contract test**

Assert the new doc and deploy README mention:
- UI owns `mcp_servers`, `plugins`, skills, OAuth tokens
- Git owns base config, images, networks, routes, personas, provider keys
- deploy merges and never overwrites UI state
- MCP JSON files are reference only
- migration order: back up, deploy merge, verify UI state, then re-add MCPs
- do not let the agent silently add MCPs

- [x] **Step 2: Run test and verify failure**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_hermes_ui_ownership_contract.py' -v`
Expected: FAIL because the doc is absent.

- [x] **Step 3: Write the docs and update stale comments**

Clarify that Google Workspace auth material is still deployed, but the MCP entry is UI-owned and must be disabled in the UI when auth is absent. Update the deploy README to remove stale skill-sync claims.

- [x] **Step 4: Run test and verify pass**

Run: `python3 -m unittest discover -s scripts/setup/tests -p 'test_hermes_ui_ownership_contract.py' -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add docs/operations/hermes-ui-ownership.md scripts/deploy/README.md services/agent/config.shared.yaml secrets/README.md .env.example scripts/setup/tests/test_hermes_ui_ownership_contract.py
git commit -m "docs: define Hermes UI ownership contract"
```

---

### Task 6: Full verification and branch review

**Files:**
- No new files.

- [x] **Step 1: Run the full setup suite**

Run: `python3 -m unittest discover -s scripts/setup/tests -v`
Expected: PASS, 0 failures.

- [x] **Step 2: Run the Hermes-adjacent suites**

Run:
```bash
python3 -m unittest discover -s services/opencode-docker-control/tests -v
python3 -m unittest discover -s services/agent/google_workspace_mcp/tests -v
```
Expected: PASS, 0 failures.

- [x] **Step 3: Shell syntax check**

Run: `bash -n scripts/deploy/deploy-agent-config.sh && bash -n scripts/maintenance/backup.sh`
Expected: exit 0.

- [x] **Step 4: Rehearse merge with temp data**

Run the helper against temp files and confirm:
- UI `mcp_servers` and `plugins` survive
- Git base `model` wins
- UI `.env` keys survive
- managed `.env` keys update
- output mode is `600`

- [x] **Step 5: Commit any final fixes**

```bash
git add -A
git commit -m "test: verify Hermes UI ownership separation"
```
