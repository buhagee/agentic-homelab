import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB = REPO_ROOT / "scripts" / "lib" / "render-config.sh"
PLACEHOLDER = "__CROWDSEC_LAPI_KEY__"
DOMAIN_PLACEHOLDER = "__QACEY_DOMAIN__"


class RenderConfigTests(unittest.TestCase):
    def run_render(self, key, domain="example.com", extra=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dynamic = Path(tmp.name) / "infrastructure" / "traefik" / "config" / "dynamic"
        dynamic.mkdir(parents=True)
        (dynamic / "middlewares.yml.tmpl").write_text(
            f"crowdsecLapiKey: \"{PLACEHOLDER}\"\n", encoding="utf-8"
        )
        (dynamic / "adguard.yml.tmpl").write_text(
            f"rule: \"Host(`adguard.{DOMAIN_PLACEHOLDER}`)\"\n", encoding="utf-8"
        )
        env = os.environ | {"CROWDSEC_LAPI_KEY": key, "QACEY_DOMAIN": domain}
        if extra:
            env.update(extra)
        result = subprocess.run(
            ["bash", "-c", f'source "{LIB}"; render_traefik_dynamic "{tmp.name}"'],
            env=env, capture_output=True, text=True,
        )
        return result, dynamic / "middlewares.yml", dynamic / "adguard.yml"

    def test_renders_key_and_domain(self):
        key = "a" * 64
        result, middlewares, adguard = self.run_render(key)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(key, middlewares.read_text())
        self.assertNotIn(PLACEHOLDER, middlewares.read_text())
        self.assertIn("adguard.example.com", adguard.read_text())
        self.assertNotIn(DOMAIN_PLACEHOLDER, adguard.read_text())

    def test_rejects_empty_key(self):
        result, middlewares, _ = self.run_render("")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(middlewares.exists())

    def test_rejects_non_hex_key(self):
        result, middlewares, _ = self.run_render("bad|key")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(middlewares.exists())

    def test_rejects_empty_domain(self):
        result, middlewares, _ = self.run_render("a" * 64, domain="")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(middlewares.exists())

    def test_rendered_files_are_gitignored(self):
        for name in ("middlewares.yml", "adguard.yml", "homeassistant.yml"):
            result = subprocess.run(
                ["git", "check-ignore", "-q",
                 f"infrastructure/traefik/config/dynamic/{name}"],
                cwd=REPO_ROOT,
            )
            self.assertEqual(result.returncode, 0, f"{name} must be gitignored")

    def test_missing_middlewares_template_fails(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dynamic = Path(tmp.name) / "infrastructure" / "traefik" / "config" / "dynamic"
        dynamic.mkdir(parents=True)
        (dynamic / "adguard.yml.tmpl").write_text("rule: x\n", encoding="utf-8")
        env = os.environ | {"CROWDSEC_LAPI_KEY": "a" * 64, "QACEY_DOMAIN": "example.com"}
        result = subprocess.run(
            ["bash", "-c", f'source "{LIB}"; render_traefik_dynamic "{tmp.name}"'],
            env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((dynamic / "middlewares.yml").exists())

    def test_rendered_mode_is_600(self):
        _, middlewares, _ = self.run_render("a" * 64)
        self.assertEqual(middlewares.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
