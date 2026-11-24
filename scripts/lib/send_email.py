#!/usr/bin/env python3
"""Send a plain-text platform alert over SMTP.

The password is read from the environment and is never included in output or
exception messages. Use this from shell scripts through scripts/lib/alert.sh.
"""
from __future__ import annotations

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from typing import Mapping


REQUIRED = ("SMTP_HOST", "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO")
ENCRYPTION_MODES = {"starttls", "ssltls", "none"}


class AlertConfigError(Exception):
    """Raised when the SMTP configuration is missing or invalid."""


def _config(env: Mapping[str, str]) -> dict[str, str]:
    missing = [key for key in REQUIRED if not env.get(key)]
    if missing:
        raise AlertConfigError(f"missing email configuration: {', '.join(missing)}")

    password = env.get("SMTP_PASSWORD", "")
    user = env.get("SMTP_USER", "")
    if bool(user) != bool(password):
        raise AlertConfigError("SMTP_USER and SMTP_PASSWORD must be set together")

    try:
        port = int(env.get("SMTP_PORT", "587"))
    except ValueError as exc:
        raise AlertConfigError("SMTP_PORT must be an integer") from exc

    encryption = env.get("SMTP_ENCRYPTION", "starttls").lower()
    if encryption not in ENCRYPTION_MODES:
        raise AlertConfigError(
            f"SMTP_ENCRYPTION must be one of {', '.join(sorted(ENCRYPTION_MODES))}"
        )

    return {
        "host": env["SMTP_HOST"],
        "port": str(port),
        "user": user,
        "password": password,
        "sender": env["ALERT_EMAIL_FROM"],
        "recipient": env["ALERT_EMAIL_TO"],
        "encryption": encryption,
    }


def send_email(
    subject: str, body: str, env: Mapping[str, str] | None = None
) -> None:
    config = _config(env if env is not None else os.environ)

    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message["Subject"] = subject
    message.set_content(body)

    host = config["host"]
    port = int(config["port"])

    if config["encryption"] == "ssltls":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)

    try:
        if config["encryption"] == "starttls":
            server.starttls()
        if config["user"] and config["password"]:
            server.login(config["user"], config["password"])
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _redact(text: str, password: str) -> str:
    if password:
        return text.replace(password, "[REDACTED]")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a Qacey platform alert email")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = _config(os.environ)
        if args.dry_run:
            print(f"ALERT_EMAIL_TO={config['recipient']} subject={args.subject}")
            return 0
        send_email(args.subject, args.body)
        return 0
    except AlertConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        password = os.environ.get("SMTP_PASSWORD", "")
        print(
            f"error: email delivery failed: {_redact(str(exc), password)}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
