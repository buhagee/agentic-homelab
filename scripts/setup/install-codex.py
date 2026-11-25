#!/usr/bin/python3
"""Plan or provision the dedicated Linux Codex account. Writes require --apply."""

import argparse
from contextlib import contextmanager
import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import sys
import tempfile

ASSETS = Path(__file__).resolve().parents[2] / "infrastructure/codex"
HOST_ROOT = Path("/")
ROOT_UID = 0
SYSTEM_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
LIB_FILES = ("codex_account.py", "qacey-codex.py", "install_runtime.py", "release.json",
             "seed_home.py", "config.toml.in", "AGENTS.md.in")
SYSTEM_UNIT_DIRS = (
    "etc/systemd/system.control", "run/systemd/system.control", "run/systemd/transient",
    "run/systemd/generator.early", "etc/systemd/system", "etc/systemd/system.attached",
    "run/systemd/system", "run/systemd/system.attached", "run/systemd/generator",
    "usr/local/lib/systemd/system", "usr/lib/systemd/system", "lib/systemd/system",
    "run/systemd/generator.late",
)


def checked_home(user, raw):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) or user == "root":
        raise ValueError("Choose a dedicated, unprivileged Linux username.")
    home = Path(raw)
    if (str(home) != raw or not home.is_absolute() or ".." in home.parts or ":" in raw
            or any(not c.isprintable() for c in raw) or not home.is_relative_to(HOST_ROOT)):
        raise ValueError("Use a canonical absolute home path without ':' or control characters.")
    parts = home.relative_to(HOST_ROOT).parts
    reserved = {"bin", "boot", "dev", "etc", "lib", "lib32", "lib64", "libx32", "proc",
                "root", "run", "sbin", "sys", "tmp", "usr", "var", "lost+found"}
    if len(parts) < 2 or parts[0] in reserved:
        raise ValueError(f"Unsafe home location: {home}")
    for disk in ("ssd", "hdd1", "hdd2"):
        platform = HOST_ROOT / "mnt" / disk / "qacey"
        if home.is_relative_to(platform) or platform.is_relative_to(home):
            raise ValueError(f"Home overlaps platform-managed storage: {platform}")
    # Reject even missing paths inside another regular user's registered home.
    for entry in pwd.getpwall():
        other = Path(entry.pw_dir)
        if (entry.pw_name != user and 1000 <= entry.pw_uid < 65534 and other.is_absolute()
                and other != HOST_ROOT and (home.is_relative_to(other) or other.is_relative_to(home))):
            raise ValueError(f"Home overlaps the registered home of {entry.pw_name}.")
    return home


def trusted(path, *, directory, optional=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022
            or (not directory and info.st_nlink != 1)):
        raise ValueError(f"Unexpected type, owner, permissions or link at {path}")
    return info


def trusted_parents(path, *, require_traversal=False):
    for directory in reversed(path.parents):
        if directory.is_relative_to(HOST_ROOT):
            info = trusted(directory, directory=True)
            # The new private GID is allocated by useradd. Require traversal under
            # either non-owner mode class without depending on supplementary groups.
            if require_traversal and info.st_mode & 0o011 != 0o011:
                raise ValueError(f"Home ancestor needs group and other search permission: {directory}")


def check_unit_collisions(name):
    for relative in SYSTEM_UNIT_DIRS:
        directory = HOST_ROOT / relative
        try:
            entries = list(directory.iterdir())
        except FileNotFoundError:
            continue
        for entry in entries:
            if entry.name in (name, f"{name}.d"):
                raise ValueError(f"Pre-existing systemd unit or drop-ins: {entry}")
            if entry.suffix in (".wants", ".requires", ".upholds"):
                dependency = entry / name
                try:
                    dependency.lstat()  # A dangling enablement link will take effect after install.
                except (FileNotFoundError, NotADirectoryError):
                    continue
                raise ValueError(f"Pre-existing systemd dependency: {dependency}")


def write_atomic(path, data, mode):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def write_record(path, record):
    write_atomic(path, (json.dumps(record, indent=2) + "\n").encode(), 0o644)


def lookup(function, name):
    try:
        return function(name)
    except KeyError:
        return None


def check_identity(record, account, group, *, check_lock):
    if (account.pw_uid == 0 or account.pw_gid == 0 or group is None
            or account.pw_gecos != record["marker"] or str(record["home"]) != account.pw_dir
            or account.pw_gid != group.gr_gid or set(group.gr_mem) - {account.pw_name}
            or set(os.getgrouplist(account.pw_name, account.pw_gid)) != {account.pw_gid}):
        raise ValueError("The recorded account, private group, home or memberships have changed.")
    if record["uid"] is not None and (account.pw_uid, account.pw_gid) != (record["uid"], record["gid"]):
        raise ValueError("The recorded account UID or GID has changed.")
    if any(entry.pw_name != account.pw_name and entry.pw_gid == account.pw_gid for entry in pwd.getpwall()):
        raise ValueError("The dedicated account shares its primary GID with another account.")
    if check_lock:
        result = subprocess.run(["/usr/bin/passwd", "--status", account.pw_name], env=SYSTEM_ENV,
                                capture_output=True, text=True, check=True)
        if result.stdout.split()[:2] != [account.pw_name, "L"]:
            raise ValueError("The dedicated account must have a locked password.")


@contextmanager
def provision_lock():
    # Both native provisioners publish account-dependent files. Keep one private inode.
    path = HOST_ROOT / "etc/qacey-dev-provision.lock"
    trusted_parents(path)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        trusted(path, directory=False)
        fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size):
            raise ValueError(f"Expected an empty, private root-owned provisioning lock at {path}")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another native provisioner is running. Retry when it finishes.") from None
        if not os.path.samestat(info, path.lstat()):
            raise ValueError("Provisioning lock changed. Review its ownership before retrying.")
        yield
    finally:
        os.close(fd)


class Provision:
    def __init__(self, user, home):
        self.user = user
        self.home = home
        self.lib = HOST_ROOT / "usr/local/lib/qacey-codex"
        self.record = HOST_ROOT / "etc/qacey-codex/installation.json"
        self.launcher = HOST_ROOT / "usr/local/bin/qacey-codex"
        self.unit = HOST_ROOT / "etc/systemd/system/qacey-codex.service"

    def preflight(self):
        trusted_parents(self.home, require_traversal=True)
        for target in (self.record.parent, self.lib, self.launcher, self.unit):
            trusted_parents(target)
        has_record_dir = trusted(self.record.parent, directory=True, optional=True)
        recorded = has_record_dir and trusted(self.record, directory=False, optional=True)
        record = json.loads(self.record.read_text()) if recorded else None
        if recorded and (record.get("schema"), record.get("user"), record.get("home")) != (
                1, self.user, str(self.home)):
            raise ValueError("Requested user or home differs from this installation's record.")
        if not recorded and has_record_dir:
            raise ValueError(f"Unrelated installation directory: {self.record.parent}")
        if not recorded:
            check_unit_collisions(self.unit.name)
        owns_lib = trusted(self.lib, directory=True, optional=True)
        if owns_lib and not recorded:
            raise ValueError(f"Unrelated installation directory: {self.lib}")
        for path in (self.launcher, self.unit, *(self.lib / name for name in LIB_FILES)):
            if trusted(path, directory=False, optional=True) and not recorded:
                raise ValueError(f"Refusing to overwrite {path}")

        account = lookup(pwd.getpwnam, self.user)
        group = lookup(grp.getgrnam, self.user)
        if account is None:
            if group is not None or (recorded and record["uid"] is not None):
                raise ValueError("Existing group or missing recorded account.")
        elif not recorded:
            raise ValueError(f"Refusing to adopt existing account {self.user}.")
        else:
            check_identity(record, account, group, check_lock=os.geteuid() == ROOT_UID)
        try:
            home_info = self.home.lstat()
        except FileNotFoundError:
            pass
        else:
            if (not recorded or account is None or not stat.S_ISDIR(home_info.st_mode)
                    or home_info.st_uid != account.pw_uid):
                raise ValueError(f"Refusing to adopt existing home {self.home}")
        return record, account

    def initial_record(self):
        # Publish ownership before useradd. Its GECOS marker identifies a partially created account.
        record = dict(schema=1, user=self.user, home=str(self.home), uid=None, gid=None,
                      marker=f"qacey-codex-{secrets.token_hex(16)}", ready=False)
        with tempfile.TemporaryDirectory(dir=self.record.parent.parent) as directory:
            temporary = Path(directory) / "record"
            temporary.mkdir()
            write_record(temporary / self.record.name, record)
            temporary.chmod(0o755)
            temporary.rename(self.record.parent)
        return record

    def prepare_home(self, account):
        # Publish a new home only when it has its final owner; a retry cannot adopt a foreign home.
        if not self.home.exists():
            with tempfile.TemporaryDirectory(dir=self.home.parent, prefix=".qacey-codex-") as staging:
                home = Path(staging) / "home"
                home.mkdir(mode=0o700)
                os.chown(home, account.pw_uid, account.pw_gid)
                home.rename(self.home)
        home_fd = os.open(self.home, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.fstat(home_fd).st_uid != account.pw_uid:
                raise ValueError(f"Unexpected home owner: {self.home}")
            os.fchown(home_fd, account.pw_uid, account.pw_gid)
            os.fchmod(home_fd, 0o700)
        finally:
            os.close(home_fd)

    def apply(self):
        self.preflight()
        with provision_lock():
            record, account = self.preflight()
            if record is None:
                record = self.initial_record()
            elif record["ready"]:
                record["ready"] = False
                write_record(self.record, record)
            if account is None:
                subprocess.run(["/usr/sbin/useradd", "--no-create-home", "--user-group", "--groups", "",
                                "--home-dir", str(self.home), "--shell", "/bin/bash", "--password", "!",
                                "--comment", record["marker"], self.user], env=SYSTEM_ENV, check=True)
                account = pwd.getpwnam(self.user)
                check_identity(record, account, grp.getgrnam(self.user), check_lock=True)
            if record["uid"] is None:
                record.update(uid=account.pw_uid, gid=account.pw_gid)
                write_record(self.record, record)

            self.prepare_home(account)
            self.lib.mkdir(mode=0o755, exist_ok=True)
            self.lib.chmod(0o755)
            for name in LIB_FILES:
                write_atomic(self.lib / name, (ASSETS / name).read_bytes(), 0o644)
            write_atomic(self.launcher, (ASSETS / "qacey-codex").read_bytes(), 0o755)
            unit = (ASSETS / "qacey-codex.service.in").read_text().replace("@USER@", self.user)
            write_atomic(self.unit, unit.encode(), 0o644)
            subprocess.run(["/usr/bin/python3", "-I", "-B", str(self.lib / "seed_home.py"), str(self.home)],
                           cwd=self.home, env=dict(SYSTEM_ENV, HOME=str(self.home)),
                           user=account.pw_uid, group=account.pw_gid, extra_groups=[], umask=0o077, check=True)
            record["ready"] = True
            write_record(self.record, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--user", default="dev-agent")
    parser.add_argument("--home", help="absolute home path (default: /home/USER)")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and os.geteuid() != ROOT_UID:
        raise PermissionError("Root is required to apply system provisioning.")
    home = checked_home(args.user, str(HOST_ROOT / "home" / args.user) if args.home is None else args.home)
    provision = Provision(args.user, home)
    print(f"Dedicated account: {args.user}\nHome: {home}\nDevelopment clones: {home / 'projects'}")
    print(f"Helpers: {provision.lib}\nLauncher: {provision.launcher}\nUnit: {provision.unit}")
    if not args.apply:
        provision.preflight()
        print("Dry run. Pass --apply as root to provision.")
        return 0
    provision.apply()
    print("Provisioned. Run qacey-codex install-runtime as the dedicated account.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(f"Codex provisioning: {exc}")
