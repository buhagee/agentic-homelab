import base64
import unittest
from email.message import EmailMessage
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG = REPO_ROOT / "services" / "agent" / "google_workspace_mcp" / "config.py"
MCP_MAIN = REPO_ROOT / "services" / "agent" / "google_workspace_mcp" / "__main__.py"
JUSTIN_MANIFEST = REPO_ROOT / "services" / "agent" / "mcp-servers.justin.json"


class GmailSurfaceContractTests(unittest.TestCase):
    def test_workspace_scopes_include_least_privilege_gmail_access(self) -> None:
        config = CONFIG.read_text(encoding="utf-8")

        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", config)
        self.assertIn("https://www.googleapis.com/auth/gmail.send", config)
        self.assertNotIn("https://mail.google.com/", config)

    def test_unified_mcp_exposes_gmail_tools(self) -> None:
        main = MCP_MAIN.read_text(encoding="utf-8")

        self.assertIn("def search_gmail_messages(", main)
        self.assertIn("def read_gmail_message(", main)
        self.assertIn("def send_gmail_message(", main)

    def test_legacy_mail_mcp_is_removed_from_justin_manifest(self) -> None:
        manifest = JUSTIN_MANIFEST.read_text(encoding="utf-8")

        self.assertNotIn('"mail_mcp"', manifest)
        self.assertNotIn("JUSTIN_GMAIL_APP_PASSWORD", manifest)

    def test_gmail_raw_message_encoding_round_trips(self) -> None:
        message = EmailMessage()
        message["To"] = "recipient@example.com"
        message["Subject"] = "Test"
        message.set_content("Hello")
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

        decoded = base64.urlsafe_b64decode(encoded).decode("utf-8")
        self.assertIn("Subject: Test", decoded)
        self.assertIn("Hello", decoded)


if __name__ == "__main__":
    unittest.main()
