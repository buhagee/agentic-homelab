import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"


class ArchonIsolationContractTests(unittest.TestCase):
    def test_start_and_build_do_not_remove_orphans(self):
        for name in ("start.sh", "build.sh"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertNotIn("--remove-orphans", text, name)

    def test_stop_only_stops_declared_services(self):
        text = (SCRIPTS / "stop.sh").read_text(encoding="utf-8")
        self.assertIn("config --services", text)
        self.assertIn('stop "${services[@]}"', text)
        self.assertNotIn("down", text)

    def test_reset_refuses_shared_project_archon(self):
        text = (SCRIPTS / "reset.sh").read_text(encoding="utf-8")
        self.assertIn("archon", text)
        self.assertIn("refusing to delete shared-project volumes", text)
        self.assertNotIn("--remove-orphans", text)


if __name__ == "__main__":
    unittest.main()
