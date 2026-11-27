#!/usr/bin/env python3
"""Check and update pinned native OpenChamber and OpenCode runtime releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / "infrastructure" / "dev-agent"
sys.path.insert(0, str(ASSETS))
import install_runtime  # noqa: E402

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


def parse_semver(version: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def classify_update(old_version: str, new_version: str) -> str | None:
    old = parse_semver(old_version)
    new = parse_semver(new_version)
    if new <= old:
        return None
    if new[0] > old[0]:
        return "major"
    if new[1] > old[1]:
        return "minor"
    return "patch"


def combine_update_types(types: list[str | None]) -> str | None:
    present = {item for item in types if item is not None}
    for level in ("major", "minor", "patch"):
        if level in present:
            return level
    return None


def select_latest_release(releases: list[dict]) -> str:
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
            continue
        tag = str(item.get("tag_name") or "").strip()
        match = SEMVER_RE.fullmatch(tag)
        if not match:
            continue
        clean = f"{int(match.group(1))}.{int(match.group(2))}.{int(match.group(3))}"
        candidates.append((parse_semver(clean), clean))
    if not candidates:
        raise ValueError("No stable semantic-version release found.")
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def fetch_github_releases(owner: str, repo: str) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=15"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "qacey-native-runtime-updater",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Unexpected releases payload from {owner}/{repo}")
    return payload


def download_file(url: str, destination: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    headers = {"User-Agent": "qacey-native-runtime-updater"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"Download exceeds size limit: {url}")
            digest.update(block)
            output.write(block)
    return digest.hexdigest()


def generate_lockfile(manifest_bytes: bytes, existing_lock_bytes: bytes) -> bytes:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required to regenerate OpenChamber package-lock.json")
    with tempfile.TemporaryDirectory(prefix="qacey-oc-lock-") as raw:
        stage = Path(raw)
        work = stage / "work"
        work.mkdir()
        (work / "package.json").write_bytes(manifest_bytes)
        if existing_lock_bytes:
            (work / "package-lock.json").write_bytes(existing_lock_bytes)
        for cfg in ("npm-userconfig", "npm-globalconfig"):
            (stage / cfg).write_text("", encoding="utf-8")
        env = dict(
            os.environ,
            NPM_CONFIG_USERCONFIG=str(stage / "npm-userconfig"),
            NPM_CONFIG_GLOBALCONFIG=str(stage / "npm-globalconfig"),
            NPM_CONFIG_CACHE=str(stage / "npm-cache"),
        )
        subprocess.run(
            [
                npm,
                "install",
                "--package-lock-only",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ],
            cwd=work,
            env=env,
            check=True,
        )
        return (work / "package-lock.json").read_bytes()


def update_release_files(
    repo_root: Path,
    *,
    openchamber_version: str | None = None,
    opencode_version: str | None = None,
    dry_run: bool = False,
) -> dict:
    dev_dir = repo_root / "infrastructure" / "dev-agent"
    release_path = dev_dir / "release.json"
    oc_runtime_dir = dev_dir / "runtime" / "openchamber"
    release = json.loads(release_path.read_text(encoding="utf-8"))

    current_oc = release["openchamber"]["version"]
    current_op = release["opencode"]["version"]

    target_oc = openchamber_version or select_latest_release(
        fetch_github_releases("openchamber", "openchamber")
    )
    target_op = opencode_version or select_latest_release(
        fetch_github_releases("anomalyco", "opencode")
    )

    oc_type = classify_update(current_oc, target_oc)
    op_type = classify_update(current_op, target_op)
    combined_type = combine_update_types([oc_type, op_type])

    changes: list[str] = []
    if oc_type is not None:
        changes.append(f"OpenChamber {current_oc} -> {target_oc} ({oc_type})")
    if op_type is not None:
        changes.append(f"OpenCode {current_op} -> {target_op} ({op_type})")

    if combined_type is None:
        return {
            "updated": False,
            "update_type": None,
            "openchamber": {"from": current_oc, "to": current_oc, "type": None},
            "opencode": {"from": current_op, "to": current_op, "type": None},
            "title": "",
            "body": "Native runtimes are already up to date.",
        }

    if not dry_run:
        with tempfile.TemporaryDirectory(prefix="qacey-native-update-") as raw:
            stage = Path(raw)
            if oc_type is not None:
                oc_url = (
                    f"https://github.com/openchamber/openchamber/releases/download/"
                    f"v{target_oc}/openchamber-web-{target_oc}.tgz"
                )
                oc_archive = stage / f"openchamber-web-{target_oc}.tgz"
                oc_sha256 = download_file(oc_url, oc_archive)
                oc_extracted = stage / "openchamber-payload"
                install_runtime.extract(oc_archive, oc_extracted, "openchamber")
                manifest_bytes = (oc_extracted / "package.json").read_bytes()
                manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
                existing_lock = (
                    (oc_runtime_dir / "package-lock.json").read_bytes()
                    if (oc_runtime_dir / "package-lock.json").exists()
                    else b""
                )
                lock_bytes = generate_lockfile(manifest_bytes, existing_lock)
                lock_sha256 = hashlib.sha256(lock_bytes).hexdigest()

                (oc_runtime_dir / "package.json").write_bytes(manifest_bytes)
                (oc_runtime_dir / "package-lock.json").write_bytes(lock_bytes)
                release["openchamber"] = {
                    "version": target_oc,
                    "url": oc_url,
                    "sha256": oc_sha256,
                    "manifest_sha256": manifest_sha256,
                    "lock_sha256": lock_sha256,
                }

            if op_type is not None:
                assets = {}
                for arch in ("x64", "arm64"):
                    op_url = (
                        f"https://github.com/anomalyco/opencode/releases/download/"
                        f"v{target_op}/opencode-linux-{arch}.tar.gz"
                    )
                    op_archive = stage / f"opencode-linux-{arch}.tar.gz"
                    op_sha256 = download_file(op_url, op_archive)
                    op_extracted = stage / f"opencode-{arch}"
                    install_runtime.extract(op_archive, op_extracted, "opencode")
                    assets[arch] = {"url": op_url, "sha256": op_sha256}
                release["opencode"] = {
                    "version": target_op,
                    "assets": assets,
                }

            release_path.write_text(
                json.dumps(release, indent=2) + "\n", encoding="utf-8"
            )

    title_parts = []
    if oc_type is not None:
        title_parts.append(f"OpenChamber v{target_oc}")
    if op_type is not None:
        title_parts.append(f"OpenCode v{target_op}")
    title = "chore(deps): update native runtime to " + " and ".join(title_parts)
    body = "Automated native development runtime update:\n\n" + "\n".join(
        f"- {line}" for line in changes
    )

    return {
        "updated": True,
        "update_type": combined_type,
        "openchamber": {
            "from": current_oc,
            "to": target_oc if oc_type else current_oc,
            "type": oc_type,
        },
        "opencode": {
            "from": current_op,
            "to": target_op if op_type else current_op,
            "type": op_type,
        },
        "title": title,
        "body": body,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Download archives and write updated pin files.")
    parser.add_argument("--check", "--dry-run", dest="dry_run", action="store_true", help="Check upstream releases without writing files.")
    parser.add_argument("--openchamber-version", help="Explicit target OpenChamber version.")
    parser.add_argument("--opencode-version", help="Explicit target OpenCode version.")
    parser.add_argument("--json-output", type=Path, help="Optional file path to write JSON summary.")
    args = parser.parse_args(argv)

    dry_run = not args.apply or args.dry_run
    summary = update_release_files(
        REPO_ROOT,
        openchamber_version=args.openchamber_version,
        opencode_version=args.opencode_version,
        dry_run=dry_run,
    )
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
