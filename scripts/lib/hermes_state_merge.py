#!/usr/bin/env python3
"""Merge Hermes UI-owned state into generated base configuration.

Hermes owns runtime integration state in ``config.yaml`` and ``.env``. Git
owns the base configuration. This helper keeps the boundary explicit:

* ``config`` copies only the UI-owned top-level YAML blocks from the live file
  into the rendered base file.
* ``env`` updates only the named repo-managed keys and preserves every other
  key, comment, and blank line.

Writes are atomic and mode 600.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_PRESERVE_KEYS = ("mcp_servers", "plugins")
TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+):(?:\s|$)")
ENV_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
VALID_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _split_top_level_blocks(text: str) -> tuple[list[str], dict[str, list[str]]]:
    """Split YAML text into top-level key blocks without parsing YAML."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        match = TOP_LEVEL_KEY_RE.match(line)
        if match:
            key = match.group(1)
            if key in blocks:
                raise ValueError(f"duplicate top-level YAML key: {key}")
            current = key
            blocks[key] = [line]
        elif current is None:
            continue
        else:
            blocks[current].append(line)

    return [], blocks


def merge_config(
    base_text: str,
    live_text: str,
    preserve_keys: Sequence[str] = DEFAULT_PRESERVE_KEYS,
) -> str:
    """Append UI-owned blocks from live config to the Git-owned base config."""
    if not base_text:
        base_text = ""

    for key in preserve_keys:
        if not VALID_KEY_RE.match(key):
            raise ValueError(f"invalid preserve key: {key!r}")

    _, base_blocks = _split_top_level_blocks(base_text)
    for key in preserve_keys:
        if key in base_blocks:
            raise ValueError(
                f"base config must not define UI-owned key {key!r}; "
                "remove it from services/agent/config.shared.yaml"
            )

    _, live_blocks = _split_top_level_blocks(live_text)

    result = base_text.rstrip()
    for key in preserve_keys:
        block = live_blocks.get(key)
        if not block:
            continue
        if result:
            result += "\n\n"
        result += "\n".join(block).rstrip()

    if result:
        result += "\n"
    return result


def merge_env(existing_text: str, managed: Mapping[str, str]) -> str:
    """Update managed keys in an env file, preserving all other content."""
    if not managed:
        return existing_text

    for key, value in managed.items():
        if not VALID_ENV_KEY_RE.match(key):
            raise ValueError(f"invalid environment key: {key!r}")
        if not isinstance(value, str):
            raise ValueError(f"environment value for {key} must be text")
        if "\n" in value or "\r" in value:
            raise ValueError(f"environment value for {key} contains a newline")

    kept: list[str] = []
    for line in existing_text.splitlines():
        match = ENV_KEY_RE.match(line)
        if match and match.group(1) in managed:
            continue
        kept.append(line)

    result = "\n".join(kept).rstrip("\n")
    if result:
        result += "\n"
    for key, value in managed.items():
        result += f"{key}={value}\n"
    return result


def write_text_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    """Write text to path atomically with the requested mode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", text=True
    )
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _config_command(args: argparse.Namespace) -> int:
    try:
        merged = merge_config(
            _read_text(Path(args.base)),
            _read_text(Path(args.live)),
            tuple(args.preserve),
        )
        write_text_atomic(Path(args.output), merged)
    except ValueError as exc:
        print(f"hermes_state_merge: {exc}", file=sys.stderr)
        return 2
    return 0


def _env_command(args: argparse.Namespace) -> int:
    managed = {key: os.environ.get(key, "") for key in args.managed_key}
    try:
        merged = merge_env(_read_text(Path(args.existing)), managed)
        write_text_atomic(Path(args.output), merged)
    except ValueError as exc:
        print(f"hermes_state_merge: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config")
    config_parser.add_argument("--base", required=True)
    config_parser.add_argument("--live", required=True)
    config_parser.add_argument("--output", required=True)
    config_parser.add_argument(
        "--preserve", action="append", default=list(DEFAULT_PRESERVE_KEYS)
    )
    config_parser.set_defaults(handler=_config_command)

    env_parser = subparsers.add_parser("env")
    env_parser.add_argument("--existing", required=True)
    env_parser.add_argument("--output", required=True)
    env_parser.add_argument("--managed-key", action="append", default=[])
    env_parser.set_defaults(handler=_env_command)

    args = parser.parse_args(argv)
    if args.command == "env" and not args.managed_key:
        parser.error("env requires at least one --managed-key")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
