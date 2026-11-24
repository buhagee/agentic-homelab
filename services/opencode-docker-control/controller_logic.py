import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("QACEY_PLATFORM_ROOT", str(Path(__file__).resolve().parents[2])))
APPROVED_FILE = Path(
    os.environ.get("QACEY_CONTROL_APPROVED", "/run/qacey-control/approved.json")
)
SNAPSHOT_FILES = ("docker-compose.platform.yml", "versions.env", ".env", "secrets/.env")
ALLOWED_ACTIONS = {"status", "logs", "start", "stop", "restart", "build", "up"}
MAX_OUTPUT = 24_000


class ControlError(Exception):
    pass


def file_hashes(root: Path = ROOT) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for relative_path in SNAPSHOT_FILES:
        path = root / relative_path
        if not path.is_file():
            result[relative_path] = None
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[relative_path] = digest
    return result


def validate_request(
    action: str, service: str, manifest: dict[str, Any], current_hashes: dict[str, str | None]
) -> None:
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise ControlError(f"Unsupported action: {action}")
    if (
        not isinstance(service, str)
        or not isinstance(manifest.get("services"), list)
        or service not in manifest["services"]
    ):
        raise ControlError(f"Service is not on the approved list: {service}")
    if manifest.get("hashes") != current_hashes:
        raise ControlError(
            "Compose or environment files changed after approval. Review the changes, then "
            "run scripts/setup/install-opencode-docker-control.py from the host terminal."
        )
    if action in {"build", "up"} and service not in manifest.get("deploy_services", []):
        raise ControlError(
            f"Build/recreate is disabled for {service}; it uses host-level Docker capabilities."
        )


def compose_command(action: str, service: str) -> list[str]:
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
    command.extend(["--project-name", "qacey-platform"])

    if action == "status":
        command.extend(["ps", "--all", service])
    elif action == "logs":
        command.extend(["logs", "--no-color", "--tail=100", service])
    elif action in {"start", "stop", "restart", "build"}:
        command.extend([action, service])
    elif action == "up":
        command.extend(["up", "-d", "--no-deps", "--build", service])
    else:
        raise ControlError(f"Unsupported action: {action}")
    return command


def _read_manifest() -> dict[str, Any]:
    try:
        data = json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ControlError(
            "Docker control is not initialized. Run "
            "scripts/setup/install-opencode-docker-control.py from the host terminal."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ControlError("The host approval file is invalid; rerun the host setup script.") from exc

    if not isinstance(data, dict) or data.get("schema") != "qacey/opencode-docker-control/v1":
        raise ControlError("The host approval file has an unsupported schema.")
    if (
        not isinstance(data.get("hashes"), dict)
        or not isinstance(data.get("services"), list)
        or not isinstance(data.get("deploy_services"), list)
    ):
        raise ControlError("The host approval file is incomplete; rerun the host setup script.")
    return data


def manage_service(action: str, service: str) -> str:
    manifest = _read_manifest()
    validate_request(action, service, manifest, file_hashes())
    timeout = 1800 if action in {"build", "up"} else 300

    try:
        result = subprocess.run(
            compose_command(action, service),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                "DOCKER_HOST": os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"),
                "HOME": "/tmp",
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            },
        )
    except FileNotFoundError as exc:
        raise ControlError("Docker CLI is unavailable in the controller.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ControlError(f"Docker {action} for {service} timed out after {timeout} seconds.") from exc

    output = result.stdout if result.returncode == 0 else result.stderr or result.stdout
    if not output:
        output = f"Docker {action} for {service} completed successfully."
    if len(output) > MAX_OUTPUT:
        output = f"[Output truncated to the last {MAX_OUTPUT} characters]\n{output[-MAX_OUTPUT:]}"
    if result.returncode != 0:
        raise ControlError(
            f"Docker {action} for {service} failed with exit code {result.returncode}:\n{output}"
        )
    return output
