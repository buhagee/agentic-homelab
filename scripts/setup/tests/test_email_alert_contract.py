import importlib.util
import io
import os
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SEND_EMAIL = REPO_ROOT / "scripts" / "lib" / "send_email.py"
ALERT_SH = REPO_ROOT / "scripts" / "lib" / "alert.sh"
EMAIL_YAML = REPO_ROOT / "infrastructure" / "crowdsec" / "notifications" / "email.yaml"
PROFILES = REPO_ROOT / "infrastructure" / "crowdsec" / "profiles.yaml"
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"
ORACLE_COMPOSE = REPO_ROOT / "docker-compose.oracle.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_ORACLE_EXAMPLE = REPO_ROOT / ".env.oracle.example"
SECRETS_README = REPO_ROOT / "secrets" / "README.md"
SETUP_README = REPO_ROOT / "scripts" / "setup" / "README.md"
MAINTENANCE_README = REPO_ROOT / "scripts" / "maintenance" / "README.md"
AGENT_DOCKERFILE = REPO_ROOT / "services" / "agent" / "Dockerfile"
CRONTAB = REPO_ROOT / "scripts" / "crontab.txt"

OPERATIONAL_FILES = [
    COMPOSE,
    ORACLE_COMPOSE,
    ENV_EXAMPLE,
    ENV_ORACLE_EXAMPLE,
    SECRETS_README,
    SETUP_README,
    MAINTENANCE_README,
    AGENT_DOCKERFILE,
    CRONTAB,
]
OPERATIONAL_FILES.extend((REPO_ROOT / "services" / "agent").glob("persona.*.md"))
OPERATIONAL_FILES.extend((REPO_ROOT / "services" / "agent").glob("config.*.yaml"))
OPERATIONAL_FILES.extend((REPO_ROOT / "infrastructure" / "backup").glob("*"))
for pattern in ("*.sh", "*.py"):
    OPERATIONAL_FILES.extend(
        p for p in (REPO_ROOT / "scripts").rglob(pattern)
        if "tests" not in p.parts and "__pycache__" not in p.parts
    )
OPERATIONAL_FILES.extend((REPO_ROOT / "infrastructure" / "crowdsec").rglob("*.yaml"))
OPERATIONAL_FILES = [path for path in OPERATIONAL_FILES if path.exists()]

GOOD_ENV = {
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "alert@example.com",
    "SMTP_PASSWORD": "app-password",
    "ALERT_EMAIL_FROM": "alert@example.com",
    "ALERT_EMAIL_TO": "admin@example.com",
    "SMTP_ENCRYPTION": "starttls",
}


class EmailAlertContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("send_email", SEND_EMAIL)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {SEND_EMAIL}")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.send_email = cls.module.send_email
        cls.main = cls.module.main
        cls.AlertConfigError = cls.module.AlertConfigError

    def test_missing_config_names_the_key_and_not_the_password(self):
        with self.assertRaises(self.AlertConfigError) as ctx:
            self.module.send_email("subject", "body", env={"SMTP_PASSWORD": "super-secret"})
        self.assertIn("SMTP_HOST", str(ctx.exception))
        self.assertNotIn("super-secret", str(ctx.exception))

    def test_starttls_login_and_message(self):
        with mock.patch.object(self.module.smtplib, "SMTP") as smtp:
            self.module.send_email("subject", "body", env=GOOD_ENV)
        smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=20)
        smtp.return_value.starttls.assert_called_once()
        smtp.return_value.login.assert_called_once_with(
            "alert@example.com", "app-password"
        )
        smtp.return_value.send_message.assert_called_once()

    def test_ssltls_uses_smtp_ssl(self):
        env = {**GOOD_ENV, "SMTP_ENCRYPTION": "ssltls", "SMTP_PORT": "465"}
        with mock.patch.object(self.module.smtplib, "SMTP_SSL") as smtp:
            self.module.send_email("subject", "body", env=env)
        smtp.assert_called_once_with("smtp.gmail.com", 465, timeout=20)

    def test_unauthenticated_relay_skips_login(self):
        env = {**GOOD_ENV, "SMTP_USER": "", "SMTP_PASSWORD": ""}
        with mock.patch.object(self.module.smtplib, "SMTP") as smtp:
            self.module.send_email("subject", "body", env=env)
        smtp.return_value.login.assert_not_called()

    def test_dry_run_does_not_connect_or_print_password(self):
        output = io.StringIO()
        with mock.patch.object(self.module.smtplib, "SMTP") as smtp:
            with mock.patch.dict(os.environ, GOOD_ENV, clear=True):
                with mock.patch("sys.stdout", output):
                    rc = self.module.main(["--subject", "subject", "--body", "body", "--dry-run"])
        self.assertEqual(rc, 0)
        smtp.assert_not_called()
        self.assertIn("ALERT_EMAIL_TO", output.getvalue())
        self.assertNotIn("app-password", output.getvalue())

    def test_bad_encryption_is_rejected(self):
        env = {**GOOD_ENV, "SMTP_ENCRYPTION": "bogus"}
        with self.assertRaises(self.AlertConfigError):
            self.module.send_email("subject", "body", env=env)

    def test_partial_auth_is_rejected(self):
        env = {**GOOD_ENV, "SMTP_PASSWORD": ""}
        with self.assertRaises(self.AlertConfigError):
            self.module.send_email("subject", "body", env=env)

    def test_auth_error_redacts_password(self):
        error = self.module.smtplib.SMTPAuthenticationError(535, b"bad app-password")
        stderr = io.StringIO()
        with mock.patch.object(self.module.smtplib, "SMTP") as smtp:
            smtp.return_value.login.side_effect = error
            with mock.patch.dict(os.environ, GOOD_ENV, clear=True):
                with mock.patch("sys.stderr", stderr):
                    rc = self.module.main(["--subject", "s", "--body", "b"])
        self.assertEqual(rc, 1)
        self.assertNotIn("app-password", stderr.getvalue())
        self.assertIn("[REDACTED]", stderr.getvalue())

    def test_alert_wrapper_uses_shared_loader_and_helper(self):
        text = ALERT_SH.read_text(encoding="utf-8")
        self.assertIn("send_email.py", text)
        self.assertIn("send_alert()", text)
        self.assertIn("platform-env.sh", text)

    def test_crowdsec_uses_email_plugin(self):
        text = EMAIL_YAML.read_text(encoding="utf-8")
        self.assertIn("type: email", text)
        self.assertIn("name: email_notif", text)
        self.assertIn("${SMTP_HOST}", text)
        self.assertIn("${SMTP_PASSWORD}", text)
        self.assertNotIn("api.telegram.org", text)

    def test_crowdsec_profile_uses_email_notifier(self):
        self.assertIn("email_notif", PROFILES.read_text(encoding="utf-8"))
        self.assertNotIn("telegram_notif", PROFILES.read_text(encoding="utf-8"))

    def test_compose_passes_smtp_not_telegram(self):
        text = COMPOSE.read_text(encoding="utf-8")
        for key in (
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USER",
            "SMTP_PASSWORD",
            "SMTP_ENCRYPTION",
            "ALERT_EMAIL_FROM",
            "ALERT_EMAIL_TO",
        ):
            self.assertIn(f"{key}=", text)
        self.assertNotIn("TELEGRAM_", text)

    def test_operational_files_have_no_telegram(self):
        for path in OPERATIONAL_FILES:
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("api.telegram.org", text, str(path))
            self.assertNotIn("TELEGRAM_", text, str(path))


if __name__ == "__main__":
    unittest.main()
