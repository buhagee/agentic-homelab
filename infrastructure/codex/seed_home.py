"""Seed a private home after the provisioner has dropped all privileges."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import stat
import sys

ASSETS = Path(__file__).resolve().parent


def directory(stack, parent_fd, name):
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    fd = os.open(name, os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    stack.callback(os.close, fd)
    if os.fstat(fd).st_uid != os.geteuid():
        raise ValueError(f"Unexpected owner of {name}")
    os.fchmod(fd, 0o700)
    return fd


def seed_file(parent_fd, name, content):
    try:
        entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if entry.st_uid != os.geteuid() or not stat.S_ISREG(entry.st_mode):
            raise ValueError(f"Unexpected existing file at {name}")
        return

    # Publish the complete seed without ever replacing an existing user file.
    temporary = f".qacey-seed-{secrets.token_hex(12)}"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    finally:
        os.unlink(temporary, dir_fd=parent_fd)


def main(home):
    if os.geteuid() == 0:
        raise PermissionError("Home seeding requires the dedicated user.")
    with ExitStack() as stack:
        home_fd = os.open(home, os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, home_fd)
        if os.fstat(home_fd).st_uid != os.geteuid():
            raise ValueError("Home belongs to a different account.")
        directory(stack, home_fd, "projects")
        state = directory(stack, home_fd, ".codex")
        local = directory(stack, home_fd, ".local")
        directory(stack, local, "bin")
        config = (ASSETS / "config.toml.in").read_text().replace(
            "@PROJECTS@", json.dumps(str(home / "projects"), ensure_ascii=False))
        seed_file(state, "config.toml", config)
        seed_file(state, "AGENTS.md", (ASSETS / "AGENTS.md.in").read_text())


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except (ValueError, OSError) as exc:
        sys.exit(f"qacey-codex home setup: {exc}")
