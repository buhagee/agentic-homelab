#!/usr/bin/env python3
"""
import-hermes-sessions.py — convert Hermes native sessions → SkillClaw sessions

Reads each Hermes agent's native `.jsonl` session logs and converts them into
the SkillClaw evolve-server session schema, writing one JSON file per session
to the shared store at {SHARED_ROOT}/{GROUP_ID}/sessions/{session_id}.json.

This replaces the (unreliable) client-proxy capture path: instead of routing
live agent traffic through the SkillClaw proxy, we read Hermes's OWN session
logs after the fact. Zero risk to the agents.

A marker file ({SHARED_ROOT}/.import-state.json) tracks which Hermes session
files (by path + mtime) have already been converted, so re-runs are idempotent
and only process new/changed sessions.

Hermes native jsonl (one JSON object per line):
  {role: session_meta, tools, model, platform, timestamp}
  {role: user, content, timestamp}
  {role: assistant, content, reasoning_content, tool_calls[], timestamp}
  {role: tool, name, content, tool_call_id, timestamp}

SkillClaw turn model (one turn = a user instruction + the assistant step that
answered it, with that step's tool calls/results folded in).
"""

from __future__ import annotations

import json
import os
import sys
import glob
from datetime import datetime, timezone

SHARED_ROOT = os.environ.get("SKILLCLAW_SHARED_ROOT", "/shared")
GROUP_ID = os.environ.get("SKILLCLAW_GROUP_ID", "qacey")
# Comma-separated "alias:/path/to/sessions" pairs.
AGENT_SESSION_DIRS = os.environ.get(
    "HERMES_SESSION_DIRS",
    "justin:/sessions/justin/sessions,annique:/sessions/annique/sessions",
)

SESSIONS_OUT = os.path.join(SHARED_ROOT, GROUP_ID, "sessions")
STATE_FILE = os.path.join(SHARED_ROOT, ".import-state.json")

# Skill-related Hermes tool names → treat as skill references for attribution.
_SKILL_READ_TOOLS = {"skill_view", "skills_list"}
_SKILL_WRITE_TOOLS = {"skill_manage"}


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def _skill_name_from_args(raw_args) -> str:
    """Best-effort extraction of a skill name from a tool-call arguments blob."""
    if not isinstance(raw_args, str):
        return ""
    try:
        a = json.loads(raw_args)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(a, dict):
        return ""
    for k in ("name", "skill", "skill_name"):
        v = a.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def convert_session(jsonl_path: str) -> dict | None:
    """Convert one Hermes .jsonl file to a SkillClaw session payload."""
    messages = []
    for line in open(jsonl_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    if not messages:
        return None

    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]

    # Index tool results by tool_call_id so we can attach them to the
    # assistant turn that issued the call.
    tool_results_by_id: dict[str, dict] = {}
    for m in messages:
        if m.get("role") == "tool":
            tcid = str(m.get("tool_call_id") or "")
            tool_results_by_id[tcid] = {
                "tool_name": str(m.get("name") or "unknown"),
                "tool_call_id": tcid,
                "content": str(m.get("content") or ""),
                "has_error": False,
                "error_type": None,
            }

    turns: list[dict] = []
    turn_num = 0
    pending_user = ""  # most recent user instruction not yet attached to a turn

    for m in messages:
        role = m.get("role")
        if role == "user":
            pending_user = str(m.get("content") or "")
        elif role == "assistant":
            turn_num += 1
            tool_calls_raw = m.get("tool_calls") or []
            tool_calls: list[dict] = []
            tool_results: list[dict] = []
            read_skills: list[dict] = []
            modified_skills: list[dict] = []

            for tc in tool_calls_raw:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                name = str(func.get("name") or "unknown")
                args = func.get("arguments")
                # Normalise arguments to a JSON-encoded string (schema requirement).
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                call_id = str(tc.get("id") or f"call_{len(tool_calls)}")
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": args},
                    }
                )
                if call_id in tool_results_by_id:
                    tool_results.append(tool_results_by_id[call_id])
                # Skill attribution
                if name in _SKILL_READ_TOOLS:
                    sn = _skill_name_from_args(args)
                    if sn:
                        read_skills.append({"skill_name": sn})
                elif name in _SKILL_WRITE_TOOLS:
                    sn = _skill_name_from_args(args)
                    if sn:
                        modified_skills.append({"skill_name": sn})

            turns.append(
                {
                    "turn_num": turn_num,
                    "prompt_text": pending_user,
                    "response_text": str(m.get("content") or ""),
                    "reasoning_content": m.get("reasoning_content") or None,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "tool_observations": [],
                    "tool_errors": [],
                    "read_skills": read_skills,
                    "modified_skills": modified_skills,
                    "injected_skills": [],
                    "prm_score": None,
                }
            )
            pending_user = ""  # consumed

    if not turns:
        return None

    return {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "num_turns": len(turns),
        "turns": turns,
    }


def main() -> int:
    os.makedirs(SESSIONS_OUT, exist_ok=True)
    state = _load_state()
    imported = 0
    skipped = 0

    for pair in AGENT_SESSION_DIRS.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        alias, sessions_dir = pair.split(":", 1)
        alias = alias.strip()
        sessions_dir = sessions_dir.strip()
        if not os.path.isdir(sessions_dir):
            print(f"[import] {alias}: dir not found: {sessions_dir}", file=sys.stderr)
            continue

        for path in sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl"))):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            key = f"{alias}:{path}"
            if state.get(key) == mtime:
                skipped += 1
                continue
            payload = convert_session(path)
            if not payload:
                state[key] = mtime
                continue
            # Namespace the output id by alias so two agents' ids never collide
            # and the evolve server attributes cross-agent sessions correctly.
            payload["session_id"] = f"{alias}-{payload['session_id']}"
            payload["user_alias"] = alias
            out_path = os.path.join(SESSIONS_OUT, f"{payload['session_id']}.json")
            tmp = out_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, out_path)
            state[key] = mtime
            imported += 1

    _save_state(state)
    print(f"[import] done: {imported} imported, {skipped} unchanged, → {SESSIONS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
