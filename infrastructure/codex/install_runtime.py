#!/usr/bin/python3 -I
"""Download and verify the reviewed installer under the dedicated account."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_account import current_account

RELEASE = Path(__file__).with_name("release.json")


def check_command(account):
    # The reviewed Linux installer publishes this absolute link through its current selection.
    expected = account.home / ".codex/packages/standalone/current/bin/codex"
    if os.path.lexists(account.codex) and (not account.codex.is_symlink() or os.readlink(account.codex) != str(expected)):
        raise ValueError(f"Refusing to replace an unrelated Codex command at {account.codex}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    account = current_account()
    check_command(account)
    release = json.loads(RELEASE.read_text())
    version = release["version"]
    print(f"Install Codex {version} into {account.bin_dir} from {release['url']}.", flush=True)
    if not args.apply:
        print("Dry run. Pass --apply to download and install.")
        return 0

    env = account.environment()
    env.update(CODEX_NON_INTERACTIVE="1", CODEX_INSTALL_DIR=str(account.bin_dir))
    with tempfile.TemporaryDirectory(prefix="qacey-codex-") as directory:
        script = Path(directory) / "install.sh"
        with urlopen(release["url"], timeout=60) as response:
            payload = response.read(1024 * 1024 + 1)
        if hashlib.sha256(payload).hexdigest() != release["sha256"]:
            raise ValueError("Official installer SHA-256 checksum differs from the reviewed pin.")
        script.write_bytes(payload)
        check_command(account)
        subprocess.run(["/bin/sh", str(script), "--release", version],
                       cwd=account.home, env=env, check=True)
    result = subprocess.run([str(account.codex), "--version"], cwd=account.home, env=env,
                            check=True, capture_output=True, text=True)
    if result.stdout.strip() != f"codex-cli {version}":
        raise ValueError(f"Unexpected installed Codex version: {result.stdout.strip()!r}")
    print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f"qacey-codex: {exc}")
