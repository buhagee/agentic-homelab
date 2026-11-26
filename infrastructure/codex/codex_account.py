"""Identity and process environment shared by the installed user commands."""

import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
from dataclasses import dataclass

RECORD = Path("/etc/qacey-codex/installation.json")
ROOT_UID = 0


@dataclass(frozen=True)
class Account:
    user: str
    home: Path

    @property
    def bin_dir(self):
        return self.home / ".local/bin"

    @property
    def codex(self):
        return self.bin_dir / "codex"

    def environment(self):
        env = {k: v for k, v in os.environ.items()
               if k in {"LANG", "TERM", "COLORTERM", "TZ", "SSH_AUTH_SOCK"} or k.startswith("LC_")}
        env.update(HOME=str(self.home), USER=self.user, LOGNAME=self.user,
                   CODEX_HOME=str(self.home / ".codex"),
                   PATH=f"{self.bin_dir}:/usr/local/bin:/usr/bin:/bin")
        return env


def checked_project(account, requested, env):
    """Reject production paths and worktrees sharing Git metadata outside the dev home."""
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


def current_account():
    uid = os.geteuid()
    if uid == 0:
        raise PermissionError("Run this command as the dedicated Codex account.")
    info = RECORD.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
        raise ValueError(f"Untrusted installation record at {RECORD}")
    record = json.loads(RECORD.read_text())
    if record.get("schema") != 1 or record.get("ready") is not True:
        raise ValueError("Root provisioning has not finished.")
    if uid != record["uid"] or os.getegid() != record["gid"]:
        raise PermissionError("Current identity differs from the recorded Codex account.")
    if set(os.getgroups()) - {record["gid"]}:
        raise PermissionError("The dedicated process must have no supplementary groups.")
    entry = pwd.getpwnam(record["user"])
    if (entry.pw_uid, entry.pw_gid, entry.pw_dir) != (uid, record["gid"], record["home"]):
        raise ValueError("The account differs from its installation record.")
    account = Account(entry.pw_name, Path(entry.pw_dir))
    for path in (account.home, account.home / ".codex", account.bin_dir):
        if path.resolve(strict=True) != path or not path.is_dir():
            raise ValueError(f"Expected a real directory at {path}")
    return account
