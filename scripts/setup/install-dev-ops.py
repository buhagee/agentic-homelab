#!/usr/bin/python3
"""Prepare the optional development operations broker; never activate services."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import pwd
import sys

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "infrastructure/dev-ops"

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

foundation = load("ops_foundation", ROOT / "scripts/setup/install-codex.py")
broker = load("ops_broker", ASSETS / "broker.py")

def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("Use the operator's sudo-authorized terminal, including preview.")
    settings = broker.validate_settings(broker.decode(args.settings.read_bytes()))
    account = broker.identity()
    operator = pwd.getpwnam(settings["operator"])
    if operator.pw_uid in (0, account.pw_uid):
        raise ValueError("Operator must differ from the development account.")
    # Dedicated opt-in paths are deliberately outside the auto-updater's managed
    # file inventory. Existing paths, units and enablement are never adopted.
    directories = [(Path("/etc/qacey-dev-ops"), 0o700),
                   (Path("/var/lib/qacey-dev-ops"), 0o700),
                   (Path("/usr/local/lib/qacey-dev-ops"), 0o755)]
    files = [
        (Path("/etc/qacey-dev-ops/policy.json"),
         (json.dumps(settings, indent=2) + "\n").encode(), 0o600),
        (Path("/usr/local/lib/qacey-dev-ops/broker.py"), (ASSETS / "broker.py").read_bytes(), 0o644),
        (Path("/usr/local/bin/qacey-dev-ops"), (ASSETS / "client.py").read_bytes(), 0o755),
        (Path("/etc/systemd/system/qacey-dev-ops.socket"),
         (ASSETS / "qacey-dev-ops.socket.in").read_text().replace("@USER@", account.pw_name).encode(), 0o644),
        (Path("/etc/systemd/system/qacey-dev-ops@.service"),
         (ASSETS / "qacey-dev-ops@.service").read_bytes(), 0o644),
    ]
    for unit in ("qacey-dev-ops.socket", "qacey-dev-ops@.service"):
        foundation.check_unit_collisions(unit)
    for path, _ in directories:
        foundation.trusted_parents(path)
        if foundation.trusted(path, directory=True, optional=True) is not None:
            raise ValueError("Existing operations installation; review before any manual upgrade.")
    for path, _, _ in files:
        if path.parent not in {directory for directory, _ in directories}:
            foundation.trusted_parents(path)
            if foundation.trusted(path, directory=False, optional=True) is not None:
                raise ValueError("Existing operations destination.")
    for path in (Path("/usr/bin/docker"), Path("/usr/bin/systemctl"), Path("/usr/bin/journalctl")):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("Required host command unavailable: " + str(path))
    print("Operations account:", account.pw_name)
    print("Approved configuration:", json.dumps(settings, indent=2))
    if not args.apply:
        print("Preview only; no host changes.")
        return
    for path, mode in directories:
        path.mkdir(mode=mode)
        path.chmod(mode)
    for path, data, mode in files:
        foundation.write_atomic(path, data, mode)
    print("Installed disabled operations socket. Verify units, then enable explicitly.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit("Operations setup refused: " + str(exc))
