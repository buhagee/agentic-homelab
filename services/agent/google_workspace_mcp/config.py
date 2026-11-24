from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

GOOGLE_WORKSPACE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)

DEFAULT_TIMEOUT_SECONDS = 60.0
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleWorkspaceConfigError(RuntimeError):
    """Raised when the Google Workspace MCP runtime is misconfigured."""


@dataclass(frozen=True)
class GoogleWorkspaceConfig:
    auth_file: Path
    user_label: str
    timeout_seconds: float
    scopes: tuple[str, ...] = GOOGLE_WORKSPACE_SCOPES

    @classmethod
    def from_env(cls) -> "GoogleWorkspaceConfig":
        auth_path = os.environ.get("GOOGLE_WORKSPACE_AUTH_FILE", "").strip()
        if not auth_path:
            raise GoogleWorkspaceConfigError(
                "GOOGLE_WORKSPACE_AUTH_FILE is required for the Google Workspace MCP. "
                "Deploy the per-user auth material before using Gmail, Drive, Docs, or Sheets."
            )

        timeout_raw = os.environ.get(
            "GOOGLE_WORKSPACE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)
        ).strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise GoogleWorkspaceConfigError(
                "GOOGLE_WORKSPACE_TIMEOUT_SECONDS must be a number."
            ) from exc

        return cls(
            auth_file=Path(auth_path),
            user_label=os.environ.get("GOOGLE_WORKSPACE_USER_LABEL", "workspace user").strip()
            or "workspace user",
            timeout_seconds=timeout_seconds,
        )


def build_authorized_user_payload(
    *, client_id: str, client_secret: str, refresh_token: str
) -> dict[str, str]:
    return {
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "token_uri": TOKEN_URI,
    }