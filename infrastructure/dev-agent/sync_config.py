"""Synchronise the fixed shared baseline; the caller must validate the account.

No provider credentials or environment-variable values are read. Only managed
MCP fields and guidance fingerprints enter sync state. A hash-only file journal
allows an unchanged interrupted operation to resume with its original baseline;
later user edits or a different baseline fail before more files are replaced.
Native JSON formatting and managed TOML-block formatting may be normalised, but
unrelated values are retained. Stop native config editors while applying sync.
"""

from contextlib import contextmanager
import copy
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tomllib

import mcp_config


BEGIN = "# BEGIN QACEY SHARED MCP\n"
END = "# END QACEY SHARED MCP\n"
LEGACY_GUIDANCE_SHA256 = "5c00de600b053d4e7de3c14690d4cd13a4cc05122bda93330726f9a6a25df7c5"
FILES = {
    "guidance": ".config/qacey-dev/AGENTS.md",
    "codex": ".codex/config.toml",
    "opencode": ".config/opencode/opencode.json",
    "codex_link": ".codex/AGENTS.md",
    "opencode_link": ".config/opencode/AGENTS.md",
    "state": ".config/qacey-dev/sync-state.json",
}
PENDING = ".config/qacey-dev/sync-pending.json"
MISSING = object()


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value):
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"


def _home(home):
    home = Path(home)
    if not home.is_absolute() or home.resolve(strict=True) != home or not home.is_dir():
        raise ValueError("The development home must be an absolute real directory.")
    if home.stat().st_uid != os.geteuid():
        raise ValueError("The development home must belong to the current account.")
    return home


def _parents(home, path, create=False):
    current = home
    for part in path.relative_to(home).parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if not create:
                continue
            current.mkdir(mode=0o700)
            info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError(f"Expected an owned real directory, not a symlink: {current}")


def _read(path, allow_link=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing", ""
    if info.st_uid != os.geteuid():
        raise ValueError(f"Unexpected owner of configuration: {path}")
    if stat.S_ISLNK(info.st_mode) and allow_link:
        return "link", os.readlink(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Expected a regular file, not a symlink: {path}")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stream:
        try:
            return "file", stream.read()
        except UnicodeError:
            raise ValueError(f"Expected UTF-8 configuration at {path}; inspect locally.") from None


def _fingerprint(kind, text):
    return "missing" if kind == "missing" else kind + ":" + _sha(text)


def _replace(path, kind, content):
    """Publish one complete private file/link in its existing directory."""
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".qacey-sync-" + secrets.token_hex(12)
    try:
        if kind == "link":
            os.symlink(content, temporary, dir_fd=parent)
        else:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


@contextmanager
def _lock(home, apply):
    path = home / ".qacey-dev-sync.lock"
    flags = os.O_NOFOLLOW | (os.O_RDWR | os.O_CREAT if apply else os.O_RDONLY)
    try:
        fd = os.open(path, flags, 0o600)
    except FileNotFoundError:
        # A first dry-run is advisory; it creates no directory or lock file.
        yield
        return
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError(f"Untrusted sync lock: {path}")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another shared configuration sync is running.") from None
        yield
    finally:
        os.close(fd)


def _state(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"schema", "baseline", "guidance", "codex", "opencode"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or any(not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key])
                   for key in ("baseline", "guidance"))
            or any(not isinstance(value[key], dict) for key in ("codex", "opencode"))):
        raise ValueError("Invalid shared sync state; inspect it locally before recovery.")
    for key in ("codex", "opencode"):
        if any(not mcp_config.NAME.fullmatch(name) or not isinstance(item, dict)
               for name, item in value[key].items()):
            raise ValueError("Invalid managed MCP state; inspect it locally before recovery.")
    return value


def _load_pending(text, baseline, snapshots):
    pending = mcp_config.parse_json(text, "interrupted sync journal")
    if (not isinstance(pending, dict)
            or set(pending) != {"schema", "baseline", "previous", "next", "files"}
            or type(pending["schema"]) is not int or pending["schema"] != 1
            or pending["baseline"] != baseline
            or not isinstance(pending["files"], dict) or set(pending["files"]) != set(FILES)):
        raise ValueError("An interrupted sync needs its original baseline and valid journal; inspect locally.")
    _state(pending["previous"])
    _state(pending["next"])
    if pending["next"] is None or pending["next"]["baseline"] != baseline:
        raise ValueError("Invalid interrupted sync state; inspect locally.")
    for key, item in pending["files"].items():
        if (not isinstance(item, dict) or set(item) != {"before", "after"}
                or any(not isinstance(v, str) or not re.fullmatch(r"missing|(?:file|link):[0-9a-f]{64}", v)
                       for v in item.values())
                or _fingerprint(*snapshots[key]) not in item.values()):
            raise ValueError(f"Configuration changed after an interrupted sync: {FILES[key]}; inspect locally.")
    return pending


def _reconcile(current, previous, desired, label):
    """Three-way merge owned leaves; preserve all unowned native values."""
    result = copy.deepcopy(current)
    for key in sorted(previous.keys() | desired.keys()):
        before, after, present = previous.get(key, MISSING), desired.get(key, MISSING), current.get(key, MISSING)
        if ((isinstance(before, dict) or before is MISSING)
                and (isinstance(after, dict) or after is MISSING)
                and (isinstance(before, dict) or isinstance(after, dict))):
            if present is not MISSING and not isinstance(present, dict):
                raise ValueError(f"Managed MCP field conflict in {label}: {key}")
            merged = _reconcile({} if present is MISSING else present,
                                {} if before is MISSING else before,
                                {} if after is MISSING else after, label)
            if merged or after is not MISSING:
                result[key] = merged
            else:
                result.pop(key, None)
        else:
            if not (type(present) is type(before) and present == before) and not (
                    type(present) is type(after) and present == after):
                raise ValueError(f"Managed MCP field conflict in {label}: {key}")
            if after is MISSING:
                result.pop(key, None)
            else:
                result[key] = copy.deepcopy(after)
    return result


def _servers(current, previous, desired, label):
    if not isinstance(current, dict) or any(not isinstance(item, dict) for item in current.values()):
        raise ValueError(f"Expected native MCP server objects in {label}.")
    result = copy.deepcopy(current)
    for name in sorted(previous.keys() | desired.keys()):
        if name not in previous:
            if name in current:
                raise ValueError(f"Unmanaged MCP server already exists in {label}: {name}; resolve the conflict locally.")
            result[name] = copy.deepcopy(desired[name])
            continue
        if name not in current and name in desired:
            raise ValueError(f"Managed MCP server changed in {label}: {name}")
        merged = _reconcile(current.get(name, {}), previous[name], desired.get(name, {}), f"{label}/{name}")
        if name not in desired:
            if merged:
                raise ValueError(f"MCP removal conflict in {label}/{name}: local client fields remain.")
            result.pop(name, None)
        else:
            result[name] = merged
    return result


def _toml(text, label):
    try:
        return tomllib.loads(text)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid TOML in {label}; inspect the file locally.") from None


def _toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value).lower()
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(_toml_value(key) + " = " + _toml_value(item) for key, item in value.items()) + " }"
    raise ValueError("Unsupported value in managed Codex MCP block; inspect locally.")


def _toml_key(value):
    return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else _toml_value(value)


def _codex(text, previous, desired, had_state):
    full = _toml(text, "Codex configuration")
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line == BEGIN]
    ends = [i for i, line in enumerate(lines) if line == END]
    if not starts and not ends:
        if had_state:
            raise ValueError("The managed Codex MCP block changed or was removed; resolve the conflict locally.")
        prefix, suffix, owned = text + ("\n" if text and not text.endswith("\n") else ""), "", {}
        outside = full
    elif len(starts) == len(ends) == 1 and starts[0] < ends[0]:
        if not had_state:
            raise ValueError("Codex already has a managed block without sync state; inspect locally.")
        start, end = starts[0], ends[0]
        prefix, suffix = "".join(lines[:start]), "".join(lines[end + 1:])
        outside = _toml(prefix + suffix, "Codex outside the managed block")
        block = _toml("".join(lines[start + 1:end]), "Codex managed block")
        if set(block) - {"mcp_servers"}:
            raise ValueError("Codex managed block contains unrelated settings; move them outside it.")
        owned = block.get("mcp_servers", {})
    else:
        raise ValueError("Malformed Codex managed block; inspect locally.")
    external = outside.get("mcp_servers", {})
    if not isinstance(external, dict) or not isinstance(owned, dict):
        raise ValueError("Expected Codex MCP server tables.")
    if external.keys() & (previous.keys() | desired.keys() | owned.keys()):
        raise ValueError("Unmanaged Codex MCP table conflicts with a shared server; relocate or remove it explicitly.")
    combined = copy.deepcopy(outside)
    if owned:
        combined.setdefault("mcp_servers", {}).update(owned)
    if combined != full:
        raise ValueError("Codex managed block is not self-contained; put native settings in explicit tables.")
    merged = _servers(owned, previous, desired, "Codex")
    body = []
    for name, fields in sorted(merged.items()):
        body.append("[mcp_servers." + _toml_value(name) + "]\n")
        body.extend(_toml_key(key) + " = " + _toml_value(value) + "\n" for key, value in fields.items())
        body.append("\n")
    result = prefix + BEGIN + "".join(body) + END + suffix
    expected = copy.deepcopy(outside)
    if merged:
        expected.setdefault("mcp_servers", {}).update(merged)
    if _toml(result, "rendered Codex configuration") != expected:
        raise ValueError("Codex managed block placement conflicts with surrounding native tables.")
    return result


def _opencode(text, previous, desired):
    config = mcp_config.parse_json(text, "OpenCode configuration") if text else {}
    if not isinstance(config, dict) or not isinstance(config.get("mcp", {}), dict):
        raise ValueError("Expected OpenCode V2 configuration with an MCP object.")
    servers = config.get("mcp", {}).get("servers", {})
    merged = _servers(servers, previous, desired, "OpenCode")
    if merged or "mcp" in config or desired or previous:
        config.setdefault("mcp", {})["servers"] = merged
    # Preserve the entire original document on semantic no-op, including formatting.
    original = mcp_config.parse_json(text, "OpenCode configuration") if text else None
    return text if config == original else _json(config)


def sync(home: Path, source: Path, apply: bool = False) -> list[str]:
    """Plan/apply the known native files; return redacted actions, [] for no-op."""
    home, source = _home(home), Path(source)
    # Baselines may be installed root-owned snapshots; only read regular files.
    source_text = []
    for name in ("AGENTS.md", "mcp.json"):
        path = source / name
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f"Expected a regular baseline file: {path}")
        source_text.append(path.read_text(encoding="utf-8"))
    guidance, manifest = source_text
    if not guidance.strip():
        raise ValueError("Shared AGENTS.md must not be empty.")
    codex, opencode = mcp_config.render(manifest, home)
    baseline = _sha(_json(source_text))
    next_state = {"schema": 1, "baseline": baseline, "guidance": _sha(guidance),
                  "codex": codex, "opencode": opencode}
    paths = {key: home / value for key, value in FILES.items()}
    pending_path = home / PENDING
    for path in [*paths.values(), pending_path, home / ".config/opencode/opencode.jsonc"]:
        _parents(home, path)
    if (home / ".config/opencode/opencode.jsonc").exists() or (home / ".config/opencode/opencode.jsonc").is_symlink():
        raise ValueError("Existing OpenCode JSONC needs explicit migration to opencode.json before shared sync.")
    with _lock(home, apply):
        snapshots = {key: _read(path, key.endswith("_link")) for key, path in paths.items()}
        state = _state(mcp_config.parse_json(snapshots["state"][1], "shared sync state")) if snapshots["state"][0] != "missing" else None
        if snapshots["state"][0] != "missing" and state is None:
            raise ValueError("Invalid null shared sync state; inspect locally.")
        pending_kind, pending_text = _read(pending_path)
        pending = _load_pending(pending_text, baseline, snapshots) if pending_kind != "missing" else None

        def prior(key):
            if pending:
                item = pending["files"][key]
                if item["before"] != item["after"] and _fingerprint(*snapshots[key]) == item["after"]:
                    return pending["next"]
                return pending["previous"]
            return state

        desired = {}
        previous_guidance = prior("guidance")
        current_kind, current_text = snapshots["guidance"]
        acceptable = {next_state["guidance"]}
        if previous_guidance:
            acceptable.add(previous_guidance["guidance"])
        if ((current_kind != "missing" and _sha(current_text) not in acceptable)
                or current_kind == "missing" and previous_guidance is not None):
            raise ValueError("Shared guidance conflict at AGENTS.md; preserve/promote the local edit explicitly.")
        desired["guidance"] = ("file", guidance)
        for key, renderer, values in (("codex", _codex, codex), ("opencode", _opencode, opencode)):
            old = prior(key)
            args = (snapshots[key][1], {} if old is None else old[key], values)
            rendered = renderer(*args, old is not None) if key == "codex" else renderer(*args)
            desired[key] = ("file", rendered)
        for key in ("codex_link", "opencode_link"):
            kind, text = snapshots[key]
            if kind == "link" and text != str(paths["guidance"]):
                raise ValueError(f"Existing AGENTS.md symlink conflicts with shared guidance: {paths[key]}")
            if kind == "file" and not (_sha(text) == next_state["guidance"] or
                    key == "codex_link" and _sha(text) == LEGACY_GUIDANCE_SHA256):
                raise ValueError(f"Custom AGENTS.md guidance needs explicit migration: {paths[key]}")
            desired[key] = ("link", str(paths["guidance"]))
        desired["state"] = ("file", _json(next_state))
        if pending and (next_state != pending["next"] or any(
                _fingerprint(*desired[key]) != pending["files"][key]["after"] for key in FILES)):
            raise ValueError("The interrupted sync no longer matches this renderer; restore its original baseline/runtime.")
        changes = [key for key in FILES if snapshots[key] != desired[key]]
        actions = [("Update " if apply else "Would update ") + str(paths[key]) for key in changes]
        if any(key in changes for key in ("codex", "opencode")):
            actions.append("Shared MCP names: " + (", ".join(sorted(codex)) or "(none)"))
        if pending:
            actions.append(("Finish" if apply else "Would finish") + " interrupted shared configuration sync.")
        if not apply or not changes and pending is None:
            return actions
        for path in [*paths.values(), pending_path]:
            _parents(home, path, create=True)
        if pending is None:
            pending = {"schema": 1, "baseline": baseline, "previous": state, "next": next_state,
                       "files": {key: {"before": _fingerprint(*snapshots[key]),
                                       "after": _fingerprint(*desired[key])} for key in FILES}}
            _replace(pending_path, "file", _json(pending))
        for key in changes:
            _parents(home, paths[key])
            if _read(paths[key], key.endswith("_link")) != snapshots[key]:
                raise ValueError(f"Configuration changed during sync: {paths[key]}; preserve the edit and inspect the journal.")
            _replace(paths[key], *desired[key])
        pending_path.unlink()
        directory = os.open(pending_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return actions


def managed_env_names(home: Path) -> set[str]:
    """Return explicit MCP environment references, never their values.

    The launcher still owns reserved process variables such as HOME and PATH.
    Read only completed sync state, not arbitrary native config or provider auth.
    """
    home = _home(home)
    path, pending = home / FILES["state"], home / PENDING
    _parents(home, path)
    with _lock(home, False):
        if _read(pending)[0] != "missing":
            raise ValueError("Finish the interrupted shared sync before starting the harness.")
        kind, text = _read(path)
        if kind == "missing":
            return set()
        state = _state(mcp_config.parse_json(text, "shared sync state"))
        if state is None:
            raise ValueError("Invalid null shared sync state; inspect locally.")
        names = set()
        for server in state["codex"].values():
            variables = server.get("env_vars", [])
            headers = server.get("env_http_headers", {})
            if not isinstance(variables, list) or not isinstance(headers, dict):
                raise ValueError("Invalid MCP environment references in shared sync state.")
            values = [*variables, *headers.values()]
            if "bearer_token_env_var" in server:
                values.append(server["bearer_token_env_var"])
            if any(not isinstance(value, str) or not mcp_config.ENV.fullmatch(value) for value in values):
                raise ValueError("Invalid MCP environment references in shared sync state.")
            names.update(values)
        return names
