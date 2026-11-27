import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "maintenance" / "update-native-runtime.py"


def load_updater():
    spec = importlib.util.spec_from_file_location("update_native_runtime", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_tar_gz(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name == "opencode" else 0o644
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class UpdateNativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.updater = load_updater()

    def test_parse_semver_and_classify_update(self):
        self.assertEqual(self.updater.parse_semver("2.8.1"), (2, 8, 1))
        self.assertEqual(self.updater.parse_semver("v2.8.1"), (2, 8, 1))
        self.assertEqual(self.updater.classify_update("2.8.0", "2.8.1"), "patch")
        self.assertEqual(self.updater.classify_update("2.8.0", "2.9.0"), "minor")
        self.assertEqual(self.updater.classify_update("2.8.0", "3.0.0"), "major")
        self.assertIsNone(self.updater.classify_update("2.8.1", "2.8.1"))
        self.assertIsNone(self.updater.classify_update("2.8.1", "2.8.0"))

    def test_combine_update_types(self):
        self.assertEqual(self.updater.combine_update_types(["patch", "major"]), "major")
        self.assertEqual(self.updater.combine_update_types(["patch", "minor"]), "minor")
        self.assertEqual(self.updater.combine_update_types(["patch", None]), "patch")
        self.assertIsNone(self.updater.combine_update_types([None, None]))

    def test_select_latest_release_skips_draft_prerelease_and_non_semver(self):
        releases = [
            {"tag_name": "v2.9.0-beta.1", "draft": False, "prerelease": True},
            {"tag_name": "v2.8.2", "draft": True, "prerelease": False},
            {"tag_name": "nightly", "draft": False, "prerelease": False},
            {"tag_name": "v2.8.0", "draft": False, "prerelease": False},
            {"tag_name": "v2.8.1", "draft": False, "prerelease": False},
        ]
        self.assertEqual(self.updater.select_latest_release(releases), "2.8.1")

    def test_update_release_files_updates_openchamber_and_opencode(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dev_dir = root / "infrastructure" / "dev-agent"
            oc_dir = dev_dir / "runtime" / "openchamber"
            oc_dir.mkdir(parents=True)
            old_pkg = b'{"name":"@openchamber/web","version":"2.8.0"}\n'
            old_lock = b'{"name":"@openchamber/web","version":"2.8.0","lockfileVersion":3}\n'
            (oc_dir / "package.json").write_bytes(old_pkg)
            (oc_dir / "package-lock.json").write_bytes(old_lock)
            (dev_dir / "release.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "opencode": {
                            "version": "2.4.1",
                            "assets": {
                                "x64": {"url": "https://example.invalid/x64.tar.gz", "sha256": "a" * 64},
                                "arm64": {"url": "https://example.invalid/arm64.tar.gz", "sha256": "b" * 64},
                            },
                        },
                        "openchamber": {
                            "version": "2.8.0",
                            "url": "https://example.invalid/oc-2.8.0.tgz",
                            "sha256": "c" * 64,
                            "manifest_sha256": hashlib.sha256(old_pkg).hexdigest(),
                            "lock_sha256": hashlib.sha256(old_lock).hexdigest(),
                        },
                    },
                    indent=2,
                )
                + "\n"
            )

            new_pkg = b'{"name":"@openchamber/web","version":"2.8.1"}\n'
            new_lock = b'{"name":"@openchamber/web","version":"2.8.1","lockfileVersion":3}\n'
            oc_tgz = make_tar_gz([("package/package.json", new_pkg)])
            op_x64 = make_tar_gz([("opencode", b"#!/bin/sh\necho opencode\n")])
            op_arm64 = make_tar_gz([("opencode", b"#!/bin/sh\necho opencode-arm\n")])

            downloads = {
                "https://github.com/openchamber/openchamber/releases/download/v2.8.1/openchamber-web-2.8.1.tgz": oc_tgz,
                "https://github.com/anomalyco/opencode/releases/download/v2.4.2/opencode-linux-x64.tar.gz": op_x64,
                "https://github.com/anomalyco/opencode/releases/download/v2.4.2/opencode-linux-arm64.tar.gz": op_arm64,
            }

            def fake_download(url, destination):
                data = downloads[url]
                destination.write_bytes(data)
                return hashlib.sha256(data).hexdigest()

            def fake_lock(manifest_bytes, existing_lock_bytes):
                self.assertEqual(manifest_bytes, new_pkg)
                return new_lock

            with patch.object(self.updater, "download_file", side_effect=fake_download), \
                 patch.object(self.updater, "generate_lockfile", side_effect=fake_lock):
                summary = self.updater.update_release_files(
                    root,
                    openchamber_version="2.8.1",
                    opencode_version="2.4.2",
                    dry_run=False,
                )

            self.assertTrue(summary["updated"])
            self.assertEqual(summary["update_type"], "patch")
            updated_release = json.loads((dev_dir / "release.json").read_text())
            self.assertEqual(updated_release["openchamber"]["version"], "2.8.1")
            self.assertEqual(updated_release["openchamber"]["sha256"], hashlib.sha256(oc_tgz).hexdigest())
            self.assertEqual(updated_release["openchamber"]["manifest_sha256"], hashlib.sha256(new_pkg).hexdigest())
            self.assertEqual(updated_release["openchamber"]["lock_sha256"], hashlib.sha256(new_lock).hexdigest())
            self.assertEqual(updated_release["opencode"]["version"], "2.4.2")
            self.assertEqual(updated_release["opencode"]["assets"]["x64"]["sha256"], hashlib.sha256(op_x64).hexdigest())
            self.assertEqual((oc_dir / "package.json").read_bytes(), new_pkg)
            self.assertEqual((oc_dir / "package-lock.json").read_bytes(), new_lock)


if __name__ == "__main__":
    unittest.main()
