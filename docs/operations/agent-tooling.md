# OpenCode tooling pick

- **Date:** 2026-11-21
- **Scope:** global `opencode-v2` config and project-local additions.
- **Stored at:** `infrastructure/opencode/config/`, bind-mounted read-only.

## Shared native Codex/OpenChamber

The [native Codex runbook](codex.md) defines a separate development account and
independent clones. Its runtime is opt-in; this OpenCode configuration and its
Docker-only MCP URLs are not automatically imported. The
[shared development runbook](development.md) adds native OpenChamber on the same
account. Personal-agent MCP migration and Hermes retirement remain separate
follow-up work. Share portable `.agents/skills`, repository guidance and the
nonsecret MCP baseline; keep plugin runtimes, models, approvals, authentication
and history native to each harness. OpenChamber UI additions stay OpenCode-local
until deliberately promoted. Baseline sync preserves unmanaged fields and rejects
managed drift. After explicit enrollment for managed updates, platform auto-deploy
applies the reviewed baseline and native runtime changes when the environment is
idle. Active coding work defers the update; Codex's tmux service is never restarted.
Provider authentication and client-local plugins/settings remain user-owned.

Use Superpowers for implementation and explicitly selected Gstack lenses for
planning/review. Install a native Codex workflow once under the dedicated account;
do not combine a plugin-owned install with manual duplicate registrations. The
existing `setup-gstack-lenses.sh` is OpenCode-specific. Native Gstack curation must
check actual discovered skill names and exclude the router/upgrade and other
non-approved skills, including nested runtime copies.

## Global core

| Role | Tool | Stars | Notes |
|---|---|---:|---|
| Code retrieval | open-codebase-index | 232 | Semantic code search; refresh with `index_codebase` when stale. |
| Terse output | caveman | local | One prose mode. No ultra/Classical-Chinese variants. |
| Citation integrity | citation-verification | 173 (`KalarisLabs`) | Crossref, OpenAlex, arXiv. |
| Systematic review | literature-review | 173 (`KalarisLabs`) | Only for PRISMA/scoping reviews. |
| TypeScript | typescript-magician | 1,975 (`mcollina/skills`) | Type-level TypeScript. |
| Research papers | academic-papers MCP | 3,131 (`paper-search-mcp`) | arXiv, PubMed, bioRxiv, medRxiv, Google Scholar. |
| Library docs | context7 MCP | 65,156 | Up-to-date library documentation. |
| Web search | searxng MCP | 39,726 + 1,376 | Private metasearch. |
| Web extraction | crawl4ai MCP | 87,583 | Crawl and extract pages. |
| Server operations | qacey-docker-control | local | Approved Compose operations only. |

The global `opencode.json` keeps the open-codebase-index plugin, the model pins,
and the global `.env`/`secrets` deny rules. Workflow plugins and commands belong
in project config.

## Removed from global

| Removed | Reason |
|---|---|
| `megacave`, `ultracave` | Duplicate caveman modes; no separate role. |
| `gstack-qa` | Depends on gstack/browser state that is not installed globally. |
| `linting-neostandard-eslint9` | No active project uses ESLint/neostandard. |
| `research-lookup` | Duplicates academic-papers + literature-review; needs Parallel API. |
| `livebench-eval` | No active role. |
| Superpowers plugin | Configured only in projects using its delivery workflow. |
| Gstack skill source and `gstack-*` commands | The curated install is shared; registration and commands are project-local. |

## Project-local options

| Need | Pick | Stars | Where |
|---|---|---:|---|
| Overall project workflow | GSD Core | 11,718 | Only projects without their own roadmap/workflow. Not OpenMacrocycle. |
| Coding workflow | Superpowers | 322,391 | Pin in project `opencode.json`; Qacey Platform opts in at its repository root. |
| Product/design decisions | Gstack approved lenses | 142,173 | Shared install at `~/.local/share/gstack`; opt in through project `skills` and local commands. Never `ship`, `land-and-deploy`, `autoplan`, `upgrade`, browser, or outside-review skills. |
| Browser/E2E | Playwright CLI + skill | 15,344 | Preferred over MCP for coding agents. |
| Browser loop with persistent state | Playwright MCP | 39,921 | Only if exploratory/self-healing loops need it. |
| Python | AAS `python-development` | source 457 | Project-local for Qacey scripts/services. |
| Linux/systemd | AAS `systemd-services` | source 1,210 | Qacey host timers/services. |
| SQL/Postgres | AAS `postgres-readonly-queries` + optional Postgres MCP | 3,490 MCP | Read-only access; do not give write credentials. |
| Long-session context pruning | Dynamic Context Pruning | 4,508 | Only after measuring context rot; one plugin, not a stack. |
| Cross-session memory | operator-memory / codemem | 520 / 82 | Only if a real recall gap appears. Not mem0 by default. |

## Do not install globally

- AAS in bulk: 3,022 skills, 50,018 stars on the catalog; too much selection
  noise and supply-chain risk. Use it as a source catalog.
- mem0, Magic Context, Chisle, opencode-snip, SonarQube, GitHub MCP,
  Micode, GoopSpec, Agent Orchestration Kit, Mission Control,
  opencode-ensemble, opencode-swarm.
- GitHub MCP: `gh` CLI is already authenticated and lower overhead.

## qacey_graph

Removed on 2026-11-21. The project-local documentation graph was stale
(271 nodes, 8 triples, 5 review items), duplicated code discovery, and required
manual `sync → extract → apply` maintenance. `open-codebase-index` covers code
retrieval, and source docs remain the authority for documented decisions.
The graph MCP, wrapper, setup script, and tests are deleted.

## OpenMacrocycle

- Keep its **Superpowers + roadmap + native background subagents + worktree
  windows** workflow. Do not add GSD Core or a fleet orchestrator.
- Its `docs/practices/gstack-lenses.md` allowed lenses use the shared install at
  `~/.local/share/gstack`. Register the source and commands in the planning
  worktree, not in Qacey's global config. Only the approved lens set is
  exposed; browser, shipping, deployment, upgrade, and outside-review skills
  stay unavailable. Invocation remains explicit and subordinate to Superpowers.
  Reproduce the install with
  `scripts/setup/setup-gstack-lenses.sh`.
- Confirmed 2026-11-21: keep the documented Superpowers, native background
  subagent, and worktree-window boundary. Do not add GSD Core or a fleet
  orchestrator. Each lane needs its own worktree, plan, disjoint write scope,
  independent review, status report to the single writer, and owner-only merge.
  No automation may bypass those gates.
- Academic-papers can support method research, but only public/synthetic
  queries. Never send private athlete/health data to public tools.
