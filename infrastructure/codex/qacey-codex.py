#!/usr/bin/python3 -I
"""Run Codex as the provisioned development account."""

import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_runtime
from codex_account import current_account


COMMANDS = {
    "version": ["--version"],
    "login": ["login", "--device-auth"],
    "login-status": ["login", "status"],
    "start": ["remote-control", "start", "--json"],
    "stop": ["remote-control", "stop", "--json"],
    "pair": ["remote-control", "pair"],
    "status": ["app-server", "daemon", "version"],
}


def checked_project(account, requested, env):
    root = account.home / "projects"
    project = Path(requested).resolve(strict=True)
    if root.resolve(strict=True) != root or root not in project.parents or not project.is_dir():
        raise ValueError(f"Select a development checkout under {root}.")
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(project), "rev-parse", "--path-format=absolute",
         "--show-toplevel", "--absolute-git-dir", "--git-common-dir"],
        env=env, cwd=account.home, capture_output=True, text=True,
    )
    paths = result.stdout.splitlines()
    if result.returncode or len(paths) != 3:
        raise ValueError(f"Expected a Git working tree at {project}.")
    for name in paths:
        path = Path(name)
        if not path.is_absolute() or root not in path.resolve(strict=True).parents:
            raise ValueError(f"Working tree and Git metadata must be under {root}.")
    return project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    operations = parser.add_subparsers(dest="operation", required=True)
    for command in COMMANDS:
        operations.add_parser(command)
    operations.add_parser("run").add_argument("project")
    operations.add_parser("install-runtime", allow_abbrev=False).add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.operation == "install-runtime":
        return install_runtime.main(["--apply"] if args.apply else [])
    account = current_account()
    env = account.environment()
    if args.operation == "run":
        command = ["-C", str(checked_project(account, args.project, env))]
    else:
        command = COMMANDS[args.operation]
    return subprocess.run([str(account.codex), *command], cwd=account.home, env=env).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f"qacey-codex: {exc}")
