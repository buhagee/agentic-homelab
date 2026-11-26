#!/usr/bin/env python3
"""Fast local secret scan used by CI and by scripts/testing/check-secrets.sh.

This complements gitleaks. It is deliberately small and dependency free so it
also runs on a host that has no network access.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATTERNS = (
    ("github-token", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{30,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("hex-secret", re.compile(r"\b[A-Fa-f0-9]{64}\b")),
)

SKIP_PARTS = {".git", "node_modules", "__pycache__", ".superpowers"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".pyc", ".lock"}


def find_violations(paths):
    violations = []
    for path in paths:
        path = Path(path)
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS:
                if name == "hex-secret" and not re.search(r"(?i)lapi|key", line):
                    continue
                if pattern.search(line):
                    violations.append((path, lineno, name))
    return violations


def iter_files(root):
    root = Path(root)
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args(argv)

    violations = find_violations(iter_files(args.root))
    for path, lineno, name in violations:
        print(f"{path}:{lineno}: possible secret ({name})", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
