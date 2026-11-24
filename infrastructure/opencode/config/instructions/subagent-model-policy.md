# Subagent model policy

Global defaults for OpenCode sessions. Project configuration overrides these
defaults where it explicitly sets an agent model or routing policy.

## Model pins

The exact `provider/model#variant` values live in the global pin files. Update
the pin, not this policy, when a model changes.

- Implementation and research: `~/.config/opencode/model-pins/implementation-research.txt`
- Planning and review: `~/.config/opencode/model-pins/planning-review.txt`

## Roles

| Responsibility | Model source |
| --- | --- |
| General implementation, exploration, bounded research, code/docs inspection | implementation-research pin |
| Planning, design, consequential synthesis | planning-review pin |
| Independent spec compliance, code quality, critical review | planning-review pin |

## Routing

- Use the built-in `plan` agent or the `planner` subagent for planning and
  design. Use `general` or `explore` for implementation, research, and
  inspection.
- Use the `reviewer` subagent for independent review. A shared pin does not mean
  a shared session; review in a fresh read-only child. Do not substitute the
  implementation model when a separate reviewer is available.
- Preserve the primary session's selected model. This policy changes agent and
  subagent defaults; it does not switch an existing session.
- If an assigned model or variant is unavailable, report it and ask before
  substituting one. Do not silently fall back.
- Project-specific model policies take precedence. Do not duplicate this policy
  into repositories or install another Superpowers copy.
- Model selection does not authorize extra delegation, production operations,
  credential access, or service restarts.
