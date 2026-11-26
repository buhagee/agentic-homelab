import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "platform-healthcheck.sh"
SERVICE = REPO_ROOT / "infrastructure" / "health" / "qacey-healthcheck.service"
TIMER = REPO_ROOT / "infrastructure" / "health" / "qacey-healthcheck.timer"
INSTALLER = REPO_ROOT / "scripts" / "maintenance" / "install-healthcheck.sh"


def arrays():
    text = SCRIPT.read_text(encoding="utf-8")
    expected = re.search(r"EXPECTED=\((.*?)\)", text, re.S).group(1).split()
    optional = re.search(r"OPTIONAL=\((.*?)\)", text, re.S).group(1).split()
    return expected, optional


def all_up_output(omit=None, omit_optional=False):
    expected, optional = arrays()
    lines = []
    for name in expected:
        if name != omit:
            lines.append(f"{name}\tUp (healthy)")
    if not omit_optional:
        for name in optional:
            lines.append(f"{name}\tUp (healthy)")
    return "\n".join(lines) + "\n"


def stopped_optional_output():
    expected, optional = arrays()
    lines = [f"{name}\tUp (healthy)" for name in expected]
    lines.extend(f"{name}\tExited (0) 2 hours ago" for name in optional)
    return "\n".join(lines) + "\n"


def run_with_fake_docker(output, fail=False):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        docker = tmp_path / "docker"
        docker.write_text(
            "#!/bin/sh\n"
            "if [ \"${FAKE_DOCKER_FAIL:-}\" = 1 ]; then echo 'docker daemon down' >&2; exit 1; fi\n"
            "cat \"$FAKE_DOCKER_OUTPUT\"\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        output_file = tmp_path / "output.txt"
        output_file.write_text(output, encoding="utf-8")
        env = {
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "FAKE_DOCKER_OUTPUT": str(output_file),
            "FAKE_DOCKER_FAIL": "1" if fail else "",
        }
        return subprocess.run(
            ["bash", str(SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            env=env,
        )


class HealthcheckContractTests(unittest.TestCase):
    def test_all_expected_healthy_is_silent(self):
        result = run_with_fake_docker(all_up_output())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_missing_expected_container_is_reported(self):
        result = run_with_fake_docker(all_up_output(omit="vaultwarden"))
        self.assertEqual(result.returncode, 0)
        self.assertIn("MISSING: vaultwarden", result.stdout)

    def test_stopped_optional_service_is_silent(self):
        result = run_with_fake_docker(stopped_optional_output())
        self.assertEqual(result.stdout.strip(), "")

    def test_stopped_legacy_containers_are_silent(self):
        legacy = ("hermes-justin", "hermes-annique", "opencode-v2", "opencode-docker-control", "mnemo-postgres")
        leftover = "".join(f"{name}\tExited (1) 2 hours ago\n" for name in legacy)
        result = run_with_fake_docker(all_up_output() + leftover)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_docker_failure_reports_docker_error(self):
        result = run_with_fake_docker("", fail=True)
        self.assertIn("DOCKER_ERROR:", result.stdout)

    def test_expected_and_optional_cover_compose_services(self):
        text = (REPO_ROOT / "docker-compose.platform.yml").read_text(encoding="utf-8")
        body = text.split("services:", 1)[1]
        body = re.split(r"^(?:volumes|networks):", body, maxsplit=1, flags=re.M)[0]
        declared = set(re.findall(r"^  ([A-Za-z0-9_.-]+):\s*$", body, re.M))
        expected, optional = arrays()
        self.assertEqual(set(expected) | set(optional), declared)

    def test_units_and_installer_exist(self):
        self.assertIn("OnCalendar=*:0/15", TIMER.read_text(encoding="utf-8"))
        self.assertIn("qacey-healthcheck", INSTALLER.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
