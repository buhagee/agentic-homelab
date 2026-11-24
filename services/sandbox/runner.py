#!/usr/bin/env python3
"""Run an agent-editable Streamlit sandbox workspace safely.

The workspace is mounted read-only into this container. Hermes writes source
files through its own /opt/data mount; this runner only executes that source.
Workspace requirements are installed into tmpfs and never into the image.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    from packaging.requirements import Requirement
except ImportError:  # pragma: no cover - packaging ships with the base image
    Requirement = None

WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
APP = Path(os.environ.get("SANDBOX_APP_PATH", "/opt/sandbox/Home.py"))
REQUIREMENTS = WORKSPACE / "requirements.txt"
DISABLED = WORKSPACE / ".disabled"
EXTRA_DIR = Path("/tmp/sandbox-extra")
PORT = os.environ.get("SANDBOX_PORT", "8501")
PYTHON = sys.executable


def log(message: str) -> None:
    print(f"[sandbox-runner] {message}", flush=True)


def requirements_hash() -> str:
    if not REQUIREMENTS.is_file():
        return "none"
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def extra_requirements(staging: Path) -> Path | None:
    """Return filtered requirements; base image packages need no download."""
    if Requirement is None:
        return REQUIREMENTS

    remaining: list[str] = []
    for raw_line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-", "git+", "http://", "https://")):
            remaining.append(raw_line)
            continue
        try:
            requirement = Requirement(line)
            installed = importlib.metadata.version(requirement.name)
        except (Exception, importlib.metadata.PackageNotFoundError):
            remaining.append(raw_line)
            continue
        if not requirement.specifier or not requirement.specifier.contains(
            installed, prereleases=True
        ):
            remaining.append(raw_line)

    if not remaining:
        return None
    filtered = staging / "requirements.filtered.txt"
    filtered.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    return filtered


def stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def install_workspace_requirements() -> bool:
    if not REQUIREMENTS.is_file():
        EXTRA_DIR.mkdir(parents=True, exist_ok=True)
        return True

    staging = EXTRA_DIR.with_name("sandbox-extra.new")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    requirement_file = extra_requirements(staging)
    if requirement_file is None:
        shutil.rmtree(EXTRA_DIR, ignore_errors=True)
        staging.rename(EXTRA_DIR)
        log("Workspace requirements already supplied by base image")
        return True
    command = [
        PYTHON,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--target",
        str(staging),
        "-r",
        str(requirement_file),
    ]
    log("Installing workspace requirements")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        log(f"Requirement install failed (exit {result.returncode}); keeping current environment")
        return False

    shutil.rmtree(EXTRA_DIR, ignore_errors=True)
    staging.rename(EXTRA_DIR)
    log("Workspace requirements ready")
    return True


def start() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{EXTRA_DIR}:{env.get('PYTHONPATH', '')}".rstrip(":")
    # Workspace packages are installed into /tmp, so Streamlit's source path
    # looks like a development checkout. Force normal server mode so explicit
    # bind/port settings remain valid.
    env["STREAMLIT_GLOBAL_DEVELOPMENTMODE"] = "false"
    command = [
        PYTHON,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--global.developmentMode=false",
        f"--server.address=0.0.0.0",
        f"--server.port={PORT}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=auto",
    ]
    log(f"Starting managed landing app {APP} on port {PORT}")
    return subprocess.Popen(command, cwd=WORKSPACE, env=env)


def main() -> int:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    process: subprocess.Popen[bytes] | None = None
    installed_hash = ""
    last_install_attempt = 0.0

    def shutdown(_signum: int, _frame: object) -> None:
        stop(process)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        if DISABLED.exists() or not APP.is_file():
            if process is not None:
                log("Workspace disabled or app missing; stopping app")
                stop(process)
                process = None
            time.sleep(3)
            continue

        current_hash = requirements_hash()
        now = time.monotonic()
        if current_hash != installed_hash and now - last_install_attempt >= 30:
            last_install_attempt = now
            stop(process)
            process = None
            if install_workspace_requirements():
                installed_hash = current_hash
            else:
                # Retry later; do not spin or repeatedly hit package indexes.
                time.sleep(5)
                continue

        if process is None or process.poll() is not None:
            if process is not None:
                log(f"App exited with code {process.returncode}; restarting")
            process = start()

        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
