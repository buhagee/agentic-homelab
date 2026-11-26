import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "testing" / "run-all.sh"


class RunAllTests(unittest.TestCase):
    def test_list_names_every_suite(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--list"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        joined = "\n".join(lines)
        for expected in (
            "scripts/setup/tests",
            "scripts/testing/tests",
            "scripts/deploy/tests",
            "bash -n",
        ):
            self.assertIn(expected, joined)


if __name__ == "__main__":
    unittest.main()
