#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


if os.geteuid() == 0:
    raise SystemExit(
        "Run as the host user, not root: the controller reads approved.json as UID 1000."
    )

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ROOT = Path(os.environ.get("QACEY_PLATFORM_ROOT", str(ROOT)))
SNAPSHOT_FILES = ("docker-compose.platform.yml", "versions.env", ".env", "secrets/.env")
EXCLUDED_SERVICES = {"opencode-docker-control"}


def compose_config() -> dict:
    command = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "docker-compose.platform.yml"),
        "--env-file",
        str(ROOT / "versions.env"),
        "--env-file",
        str(ROOT / ".env"),
    ]
    secrets_file = ROOT / "secrets/.env"
    if secrets_file.is_file():
        command.extend(["--env-file", str(secrets_file)])
    command.extend(["--project-name", "qacey-platform", "config", "--format", "json"])
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker compose config failed:\n{result.stderr[-4000:]}")
    return json.loads(result.stdout)


def file_hashes() -> dict[str, str | None]:
    hashes = {}
    for relative_path in SNAPSHOT_FILES:
        path = ROOT / relative_path
        hashes[relative_path] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return hashes


def deploy_allowed(service: dict) -> bool:
    if (
        service.get("privileged")
        or service.get("network_mode") == "host"
        or service.get("pid") == "host"
        or service.get("ipc") == "host"
        or service.get("uts") == "host"
        or service.get("cap_add")
        or service.get("devices")
    ):
        return False

    for volume in service.get("volumes", []):
        if isinstance(volume, dict) and volume.get("source") == "/var/run/docker.sock":
            return False
    return True


def main() -> None:
    if ROOT != EXPECTED_ROOT or Path("/.dockerenv").exists():
        raise SystemExit(
            "Run this setup from the host terminal, not from inside the OpenCode container."
        )

    config = compose_config()
    services = config.get("services", {})
    approved_services = sorted(set(services) - EXCLUDED_SERVICES)
    deploy_services = sorted(
        name
        for name in approved_services
        if deploy_allowed(services[name])
    )
    manifest = {
        "schema": "qacey/opencode-docker-control/v1",
        "hashes": file_hashes(),
        "services": approved_services,
        "deploy_services": deploy_services,
    }

    destination = Path.home() / ".local/share/qacey-opencode-control"
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=destination, delete=False
    ) as temporary:
        json.dump(manifest, temporary, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(destination / "approved.json")
    print(
        f"Approved {len(approved_services)} Qacey services "
        f"({len(deploy_services)} may build/recreate)."
    )
    print(f"Approval snapshot: {destination / 'approved.json'}")


if __name__ == "__main__":
    main()
