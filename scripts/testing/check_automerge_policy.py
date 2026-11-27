#!/usr/bin/env python3
"""Guard Renovate's review bypass: bot PRs may only change versions.env.

Renovate now automerges patch and minor updates for both stateless and stateful
services. Major updates remain manual.
Humans are not constrained here; their PRs still need a green CI run and a merge
through the protected branch rules.
"""

from __future__ import annotations

import argparse
import sys


NATIVE_RUNTIME_FILES = frozenset(
    {
        "infrastructure/dev-agent/release.json",
        "infrastructure/dev-agent/runtime/openchamber/package.json",
        "infrastructure/dev-agent/runtime/openchamber/package-lock.json",
    }
)


def is_renovate_bot(author: str) -> bool:
    name = (author or "").lower()
    return name.endswith("[bot]") and "renovate" in name


def evaluate(author: str, labels, changed_files):
    """Return a failure reason, or None when the PR may merge."""
    if not is_renovate_bot(author):
        return None

    files = {path.strip() for path in changed_files if path.strip()}
    if files == {"versions.env"}:
        return None
    if (
        files
        and files <= NATIVE_RUNTIME_FILES
        and "infrastructure/dev-agent/release.json" in files
    ):
        return None
    return "Renovate PR changes files other than versions.env or native runtime pins"


def split_values(raw: str):
    return [part for part in raw.replace("\n", ",").split(",") if part.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--author", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--changed-files", default="")
    args = parser.parse_args(argv)

    reason = evaluate(
        args.author, split_values(args.labels), split_values(args.changed_files)
    )
    if reason:
        print(f"automerge policy: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
