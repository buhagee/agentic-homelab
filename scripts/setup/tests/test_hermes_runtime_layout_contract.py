import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "services" / "agent" / "Dockerfile"
START = REPO_ROOT / "services" / "agent" / "start.sh"
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
MANIFEST = REPO_ROOT / "docs" / "operations" / "hermes-mcp-reference" / "mcp-servers.shared.json"
BACKUP = REPO_ROOT / "scripts" / "maintenance" / "backup.sh"
DOC = REPO_ROOT / "docs" / "operations" / "hermes-ui-ownership.md"


def compose_block(name):
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"  {name}:\n", 1)[1].split("\n  # ──", 1)[0]


class HermesRuntimeLayoutContractTests(unittest.TestCase):
    def test_image_home_is_inside_the_managed_data_root(self):
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("ENV HOME=/opt/data/home", text)
        self.assertNotIn("ENV HOME=/opt/hermes/home", text)
        self.assertIn("ln -s /opt/data/home /opt/hermes/home/.hermes", text)

    def test_start_script_creates_the_data_home(self):
        text = START.read_text(encoding="utf-8")
        self.assertIn('export HOME="${HOME:-/opt/data/home}"', text)
        self.assertIn('mkdir -p "$HOME"', text)
        self.assertIn('ln -s /opt/data/skills "$HOME/skills"', text)

    def test_both_agents_mount_home_and_skills_under_data(self):
        for service, user in (("hermes-justin", "justin"), ("hermes-annique", "annique")):
            block = compose_block(service)
            self.assertIn("HOME: /opt/data/home", block, service)
            self.assertIn("HERMES_HOME: /opt/data", block, service)
            self.assertIn("HERMES_WRITE_SAFE_ROOT: /opt/data", block, service)
            self.assertIn(
                f"/mnt/ssd/qacey/hermes/{user}/home:/opt/data/home",
                block,
                service,
            )
            self.assertIn(
                "/mnt/ssd/qacey/hermes/skills/shared:/opt/data/skills/shared:ro",
                block,
                service,
            )
            self.assertIn(
                f"/mnt/ssd/qacey/hermes/skills/{user}:/opt/data/skills/{user}:rw",
                block,
                service,
            )
            self.assertNotIn("/opt/hermes/home", block, service)

    def test_reference_manifest_uses_data_home(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["google_workspace"]["env"]["HOME"], "/opt/data/home")

    def test_backup_covers_tool_home_and_ui_skills(self):
        text = BACKUP.read_text(encoding="utf-8")
        self.assertIn("/mnt/ssd/qacey/hermes/justin/home", text)
        self.assertIn("/mnt/ssd/qacey/hermes/justin/data/skills", text)

    def test_docs_describe_the_layout_and_migration(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("/opt/data/home", text)
        self.assertIn("/opt/data/skills", text)
        self.assertIn("HERMES_DASHBOARD_FILES_ROOT", text)


if __name__ == "__main__":
    unittest.main()
