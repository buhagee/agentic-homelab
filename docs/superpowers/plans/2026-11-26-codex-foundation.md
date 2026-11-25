# Codex Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a usable opt-in Codex runtime without changing or granting writes to existing server deployments.

**Architecture:** Separate root provisioning from a non-root pinned runtime install and manual authentication/activation. A common launcher keeps CLI and systemd on one account/state directory. Development uses independent clones under the new account's projects root.

**Tech Stack:** Python 3.11+ standard library, Linux accounts, systemd, official Codex installer, unittest.

**Spec:** [Additive Linux Codex foundation](../../designs/2026-11-26-codex-foundation.md)

## Global Constraints

- Codex version is `0.172.0`; installer URL/hash and all public command names are fixed by the spec.
- Default account is `dev-agent`; default home is `/home/dev-agent`.
- Both installers default to dry-run; root provisioning requires `--apply`, runtime installation requires a matching non-root user and `--apply`.
- No existing project ownership/ACL changes, production checkout mutation, credential reads, service activation, or deployment calls.
- Root-owned installation record and helpers; private user-owned state; seed config/guidance only when absent.
- Offline tests use temporary paths and process/OS adapters; never exercise real accounts, credentials or services.
- One development checkout/worktree owner; no common Git directory shared with a live checkout.
- Only the first additive PR is in scope. Do not remove Hermes or add OpenChamber/A2A yet.

## Review Focus

- A symlink or pre-existing unrelated target must fail before root writes; test destination preflight.
- A repeat invocation must preserve user config and authentication; test non-default content remains unchanged.
- A wrong user or root runtime invocation must fail before download/execution; test call ordering.
- A Git worktree inside the dev root can still share production metadata outside it; test common-dir rejection.
- A service marked active can have a dead detached daemon; test passive status command and document the limitation.

## Task 1: Host foundation and executable contracts

**Files:**
- Create `scripts/setup/install-codex.py`.
- Create `infrastructure/codex/qacey-codex.py`, `install_runtime.py`, `release.json`, config/guidance/unit templates and a small shared helper if it removes actual duplication.
- Create focused `scripts/setup/tests/test_codex_*.py` behavior tests.

**Interfaces:**
- Consumes the exact CLI/account/path/runtime contracts in the spec.
- Produces `python3 scripts/setup/install-codex.py [--user NAME] [--home PATH] [--apply]` and the `qacey-codex` operations table from the spec.

- [x] Write behavior tests for the review-focus cases and dry-run/install/lifecycle contracts; observe the expected failures.
- [x] Implement the minimal provisioning, launcher and pinned runtime helpers. Use argv arrays and standard library parsing; no shell-interpolated user paths.
- [x] Run focused tests and validate generated TOML/unit syntax where available; retain evidence of remaining host acceptance checks.
- [x] Self-review, commit only this task's files, and report paths, commit, test result and limitations for independent review.

## Task 2: Operations guide and integration review

**Files:**
- Create `docs/operations/codex.md`.
- Update `AGENTS.md`, `README.md` and `docs/operations/agent-tooling.md` with concise navigation and the dedicated-runtime boundary.
- Update this plan's completion state after evidence is available.

**Interfaces:**
- Consumes Task 1's public commands and rendered layout.
- Produces a complete install, clone, login, pairing, service, sudo handoff, update, backup and rollback runbook.

- [x] Document the source-confirmed deploy chain, unresolved live path, separate clone decision and merge-triggered existing deployment.
- [x] Describe explicit native Superpowers/Gstack setup, avoiding duplicate/global workflow installs and the OpenCode-specific installer.
- [x] Run `bash scripts/testing/run-all.sh`, the existing public hygiene/secret checks and `git diff --check` on the integrated tree.
- [x] Obtain independent whole-branch review and fix material findings.
- [x] Publish the branch and create a review PR against `main`; inspect CI and leave the PR unmerged.
