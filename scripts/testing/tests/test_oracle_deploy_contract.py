import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ORACLE = REPO_ROOT / "scripts" / "deploy" / "oracle-deploy.sh"
REPAIR = REPO_ROOT / "scripts" / "maintenance" / "crowdsec-repair.sh"
PASSTHROUGH = REPO_ROOT / "infrastructure" / "traefik" / "oracle" / "dynamic" / "passthrough.yml"


class OracleDeployContractTests(unittest.TestCase):
    def test_domain_is_validated_before_containers_are_removed(self):
        text = ORACLE.read_text(encoding="utf-8")
        self.assertLess(
            text.index("QACEY_DOMAIN not set"),
            text.index("Stop any pre-existing"),
            "validate .env.oracle before tearing down the edge",
        )

    def test_passthrough_template_uses_the_domain_variable(self):
        text = PASSTHROUGH.read_text(encoding="utf-8")
        self.assertIn("${QACEY_DOMAIN}", text)

    def test_repair_renders_the_domain_and_probes_it(self):
        text = REPAIR.read_text(encoding="utf-8")
        self.assertIn("${QACEY_DOMAIN}", text)
        self.assertNotIn("example.com", text)

    def test_next_steps_use_configured_values(self):
        text = ORACLE.read_text(encoding="utf-8")
        self.assertIn("${QACEY_DOMAIN}", text)
        self.assertNotIn("example.com", text)
        self.assertNotIn("203.0.113.10", text)

    def test_repair_probes_a_live_host(self):
        text = REPAIR.read_text(encoding="utf-8")
        self.assertNotIn("files.${QACEY_DOMAIN}", text)
        self.assertIn("vault.${QACEY_DOMAIN}", text)


if __name__ == "__main__":
    unittest.main()
