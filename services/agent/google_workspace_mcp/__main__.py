from __future__ import annotations

import base64
import io
import mimetypes
import re
import tempfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httplib2
from google.auth.transport.requests import Request
from google_auth_httplib2 import AuthorizedHttp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .config import GoogleWorkspaceConfig, GoogleWorkspaceConfigError

DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
SLIDES_MIME = "application/vnd.google-apps.presentation"
TEXTUAL_MIME_PREFIXES = ("text/",)
TEXTUAL_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
}

mcp = FastMCP(
    "google-workspace",
    instructions=(
        "Unified Google Workspace tools for Gmail, Google Drive, Docs, and Sheets. "
        "Use search_drive_items to find files and folders, read_drive_item for Drive-backed "
        "content, save_text_to_drive for explicit file saves, create/read/update_google_doc "
        "for Docs, create/read/update_google_sheet for Sheets, and the Gmail tools for "
        "mail search, reading, and explicit sending."
    ),
)

GOOGLE_CONVERTIBLE_MIME_BY_EXTENSION = {
    ".csv": SHEET_MIME,
    ".tsv": SHEET_MIME,
    ".ods": SHEET_MIME,
    ".xls": SHEET_MIME,
    ".xlsx": SHEET_MIME,
    ".doc": DOC_MIME,
    ".docx": DOC_MIME,
    ".odt": DOC_MIME,
    ".rtf": DOC_MIME,
    ".txt": DOC_MIME,
    ".md": DOC_MIME,
    ".markdown": DOC_MIME,
    ".html": DOC_MIME,
    ".htm": DOC_MIME,
    ".ppt": SLIDES_MIME,
    ".pptx": SLIDES_MIME,
    ".odp": SLIDES_MIME,
}

DEFAULT_EXPORT_MIME_BY_SOURCE = {
    DOC_MIME: "application/pdf",
    SHEET_MIME: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    SLIDES_MIME: "application/pdf",
}

EXPORT_EXTENSION_BY_MIME = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def _config() -> GoogleWorkspaceConfig:
    return GoogleWorkspaceConfig.from_env()


def _load_credentials() -> Credentials:
    config = _config()
    if not config.auth_file.exists():
        raise GoogleWorkspaceConfigError(
            "Google Workspace access is not configured for "
            f"{config.user_label}. Missing auth file at {config.auth_file}."
        )

    credentials = Credentials.from_authorized_user_file(
        str(config.auth_file), list(config.scopes)
    )
    if not credentials.refresh_token:
        raise GoogleWorkspaceConfigError(
            "Google Workspace auth file is present but does not contain a refresh token. "
            "Re-run the OAuth consent bootstrap for this user."
        )

    if not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            config.auth_file.write_text(credentials.to_json(), encoding="utf-8")
        else:
            raise GoogleWorkspaceConfigError(
                "Google Workspace credentials are invalid and cannot be refreshed. "
                "Re-run the OAuth consent bootstrap for this user, including Gmail access."
            )

    return credentials


def _service(name: str, version: str):
    config = _config()
    authorized_http = AuthorizedHttp(
        _load_credentials(),
        http=httplib2.Http(timeout=config.timeout_seconds),
    )
    return build(
        name,
        version,
        http=authorized_http,
        cache_discovery=False,
    )


def _drive_service():
    return _service("drive", "v3")


def _docs_service():
    return _service("docs", "v1")


def _sheets_service():
    return _service("sheets", "v4")


def _gmail_service():
    return _service("gmail", "v1")


def _gmail_header(payload: dict[str, Any], name: str) -> str:
    wanted = name.lower()
    for header in payload.get("headers", []):
        if str(header.get("name", "")).lower() == wanted:
            return str(header.get("value", ""))
    return ""


def _decode_gmail_body(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _gmail_content(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    def visit(part: dict[str, Any]) -> None:
        filename = str(part.get("filename", ""))
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        if filename or attachment_id:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": part.get("mimeType", ""),
                    "size": body.get("size", 0),
                }
            )
            return

        mime_type = str(part.get("mimeType", "")).lower()
        decoded = _decode_gmail_body(str(body.get("data", "")))
        if decoded and mime_type == "text/plain":
            plain_parts.append(decoded)
        elif decoded and mime_type == "text/html":
            html_parts.append(decoded)
        for child in part.get("parts", []) or []:
            visit(child)

    visit(payload)
    body = "\n\n".join(plain_parts).strip()
    if not body:
        body = "\n\n".join(html_parts).strip()
    return body[:30000], attachments


def _gmail_message(message_id: str, include_body: bool = False) -> dict[str, Any]:
    request = _gmail_service().users().messages().get(
        userId="me",
        id=message_id.strip(),
        format="full" if include_body else "metadata",
        metadataHeaders=["From", "To", "Cc", "Subject", "Date", "Message-ID"],
    )
    message = request.execute()
    payload = message.get("payload", {})
    result: dict[str, Any] = {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "label_ids": message.get("labelIds", []),
        "snippet": message.get("snippet", ""),
        "from": _gmail_header(payload, "From"),
        "to": _gmail_header(payload, "To"),
        "cc": _gmail_header(payload, "Cc"),
        "subject": _gmail_header(payload, "Subject"),
        "date": _gmail_header(payload, "Date"),
    }
    if include_body:
        body, attachments = _gmail_content(payload)
        result["body"] = body
        result["attachments"] = attachments
    return result


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


@mcp.tool()
def search_gmail_messages(
    query: str = "",
    limit: int = 10,
    include_body: bool = False,
    include_spam_trash: bool = False,
) -> dict[str, Any]:
    """Search Gmail using Gmail search syntax.

    Args:
        query: Gmail query such as `from:shop.example newer_than:7d` or
            `is:unread`. Empty query lists recent messages.
        limit: Maximum messages to return (1-25).
        include_body: Include truncated message bodies and attachment metadata.
        include_spam_trash: Include spam and trash when true.
    """
    try:
        limit = max(1, min(int(limit), 25))
        response = _gmail_service().users().messages().list(
            userId="me",
            q=query.strip() or None,
            maxResults=limit,
            includeSpamTrash=include_spam_trash,
        ).execute()
        messages = [
            _gmail_message(item["id"], include_body=include_body)
            for item in response.get("messages", [])
            if item.get("id")
        ]
        return {"messages": messages, "result_size_estimate": response.get("resultSizeEstimate", 0)}
    except Exception as exc:
        _handle_error("Gmail search", exc)


@mcp.tool()
def read_gmail_message(message_id: str) -> dict[str, Any]:
    """Read one Gmail message by ID, including text body and attachment metadata."""
    try:
        if not message_id.strip():
            raise ToolError("message_id is required.")
        return _gmail_message(message_id, include_body=True)
    except Exception as exc:
        _handle_error("Gmail read", exc)


@mcp.tool()
def send_gmail_message(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    reply_to_message_id: str = "",
) -> dict[str, Any]:
    """Send an explicitly requested plain-text Gmail message.

    Args:
        to: Recipient email address or comma-separated addresses.
        subject: Email subject.
        body: Plain-text email body.
        cc: Optional comma-separated CC addresses.
        bcc: Optional comma-separated BCC addresses.
        reply_to_message_id: Optional message ID to reply within its thread.
    """
    try:
        recipients = [item.strip() for item in to.split(",") if item.strip()]
        if not recipients:
            raise ToolError("At least one recipient is required.")
        if not subject.strip():
            raise ToolError("Subject is required.")
        if not body.strip():
            raise ToolError("Body is required.")

        message = EmailMessage()
        message["To"] = ", ".join(recipients)
        if cc.strip():
            message["Cc"] = cc.strip()
        if bcc.strip():
            message["Bcc"] = bcc.strip()
        message["Subject"] = subject.strip()

        request_body: dict[str, Any] = {}
        if reply_to_message_id.strip():
            original = _gmail_service().users().messages().get(
                userId="me",
                id=reply_to_message_id.strip(),
                format="metadata",
                metadataHeaders=["Message-ID", "References"],
            ).execute()
            original_payload = original.get("payload", {})
            message_id_header = _gmail_header(original_payload, "Message-ID")
            references = _gmail_header(original_payload, "References").strip()
            if message_id_header:
                message["In-Reply-To"] = message_id_header
                message["References"] = f"{references} {message_id_header}".strip()
            request_body["threadId"] = original.get("threadId")

        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        request_body["raw"] = raw
        sent = _gmail_service().users().messages().send(
            userId="me",
            body=request_body,
        ).execute()
        return {
            "action": "sent",
            "id": sent.get("id"),
            "thread_id": sent.get("threadId"),
            "label_ids": sent.get("labelIds", []),
        }
    except Exception as exc:
        _handle_error("Gmail send", exc)


def _move_file_to_parent(file_id: str, parent_id: str) -> None:
    cleaned_parent_id = parent_id.strip()
    if not cleaned_parent_id:
        return

    drive_files = _drive_service().files()
    metadata = drive_files.get(
        fileId=file_id,
        fields="parents",
        supportsAllDrives=True,
    ).execute()
    current_parents = [
        existing_parent
        for existing_parent in metadata.get("parents", [])
        if existing_parent and existing_parent != cleaned_parent_id
    ]

    update_kwargs: dict[str, Any] = {
        "fileId": file_id,
        "addParents": cleaned_parent_id,
        "fields": "id,parents",
        "supportsAllDrives": True,
    }
    if current_parents:
        update_kwargs["removeParents"] = ",".join(current_parents)

    drive_files.update(**update_kwargs).execute()


def _decode_bytes(data: bytes, mime_type: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(
            f"Drive item with MIME type '{mime_type}' is not readable as UTF-8 text. "
            "Use Google Docs or Google Sheets tools, or save a text export instead."
        ) from exc


def _download_media(request, mime_type: str) -> str:
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return _decode_bytes(buffer.getvalue(), mime_type)


def _extract_doc_text(content_blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []

    def visit(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            paragraph = block.get("paragraph")
            if paragraph:
                for element in paragraph.get("elements", []):
                    text_run = element.get("textRun")
                    if text_run and text_run.get("content"):
                        parts.append(text_run["content"])

            table = block.get("table")
            if table:
                for row in table.get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        visit(cell.get("content", []))

            table_of_contents = block.get("tableOfContents")
            if table_of_contents:
                visit(table_of_contents.get("content", []))

    visit(content_blocks)
    return "".join(parts).strip()


def _doc_content_end_index(document: dict[str, Any]) -> int:
    content = document.get("body", {}).get("content", [])
    if not content:
        return 1
    return max(block.get("endIndex", 1) for block in content)


def _default_sheet_range(spreadsheet_id: str) -> str:
    sheets = _sheet_tabs(spreadsheet_id)
    if not sheets:
        raise ToolError("Google Sheet does not contain any tabs to read.")
    return sheets[0]["title"]


def _sheet_tabs(spreadsheet_id: str) -> list[dict[str, Any]]:
    metadata = _sheets_service().spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields=(
            "sheets.properties(sheetId,title,index,hidden,gridProperties(rowCount,columnCount))"
        ),
    ).execute()
    tabs: list[dict[str, Any]] = []
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        tabs.append(
            {
                "sheetId": properties.get("sheetId"),
                "title": properties.get("title", ""),
                "index": properties.get("index", 0),
                "hidden": bool(properties.get("hidden", False)),
                "rowCount": properties.get("gridProperties", {}).get("rowCount"),
                "columnCount": properties.get("gridProperties", {}).get("columnCount"),
            }
        )
    return tabs


def _drive_item_metadata(file_id: str) -> dict[str, Any]:
    return _drive_service().files().get(
        fileId=file_id,
        fields="id,name,mimeType,webViewLink,modifiedTime,parents,trashed",
        supportsAllDrives=True,
    ).execute()


def _drive_query(
    *,
    query: str | None,
    fields: str = "files(id,name,mimeType,webViewLink,modifiedTime,parents,trashed)",
    page_size: int = 100,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        response = _drive_service().files().list(
            q=query,
            pageSize=min(max(page_size, 1), 1000),
            fields=f"nextPageToken,{fields}",
            corpora="allDrives",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageToken=page_token,
        ).execute()
        items.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items


def _find_folder_by_name(name: str, parent_id: str = "") -> dict[str, Any] | None:
    filters = [f"mimeType = '{FOLDER_MIME}'", f"name = '{_escape_query(name)}'", "trashed = false"]
    if parent_id.strip():
        filters.append(f"'{_escape_query(parent_id.strip())}' in parents")
    matches = _drive_query(query=" and ".join(filters), page_size=25)
    return matches[0] if matches else None


def _ensure_folder_path(folder_path: str, parent_id: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_parent = parent_id.strip()
    existing: list[dict[str, Any]] = []
    created: list[dict[str, Any]] = []
    for raw_part in folder_path.split("/"):
        part = raw_part.strip()
        if not part:
            continue
        folder = _find_folder_by_name(part, current_parent)
        if folder is None:
            body: dict[str, Any] = {"name": part, "mimeType": FOLDER_MIME}
            if current_parent:
                body["parents"] = [current_parent]
            folder = _drive_service().files().create(
                body=body,
                fields="id,name,mimeType,webViewLink,modifiedTime,parents",
                supportsAllDrives=True,
            ).execute()
            created.append(folder)
        else:
            existing.append(folder)
        current_parent = folder["id"]
    return existing, created


def _resolve_upload_mime_type(name: str, mime_type: str) -> str:
    resolved = mime_type.strip()
    if not resolved:
        guessed, _ = mimetypes.guess_type(name)
        resolved = guessed or "application/octet-stream"
    if resolved.startswith("application/vnd.google-apps."):
        raise ToolError(
            "Google-native MIME types must use the dedicated tools: "
            "create_google_doc, create_google_sheet, or create_drive_folder."
        )
    return resolved


def _resolve_google_conversion_target(path: Path, convert_to_google_format: bool) -> str | None:
    if not convert_to_google_format:
        return None
    return GOOGLE_CONVERTIBLE_MIME_BY_EXTENSION.get(path.suffix.lower())


def _sheet_id_by_title(spreadsheet_id: str, sheet_title: str) -> int:
    cleaned_title = sheet_title.strip()
    for tab in _sheet_tabs(spreadsheet_id):
        if tab["title"] == cleaned_title:
            sheet_id = tab.get("sheetId")
            if sheet_id is None:
                break
            return int(sheet_id)
    raise ToolError(f"Google Sheet tab '{cleaned_title}' was not found.")


def _sheet_tab_by_title(spreadsheet_id: str, sheet_title: str) -> dict[str, Any]:
    cleaned_title = sheet_title.strip()
    for tab in _sheet_tabs(spreadsheet_id):
        if tab["title"] == cleaned_title:
            return tab
    raise ToolError(f"Google Sheet tab '{cleaned_title}' was not found.")


def _sheet_title_from_range(range_name: str) -> str | None:
    cleaned = range_name.strip()
    if not cleaned or "!" not in cleaned:
        return None
    sheet_title = cleaned.split("!", 1)[0].strip()
    if sheet_title.startswith("'") and sheet_title.endswith("'"):
        sheet_title = sheet_title[1:-1].replace("''", "'")
    return sheet_title or None


def _column_index_from_letters(column_letters: str) -> int:
    value = 0
    for char in column_letters.upper():
        if not ("A" <= char <= "Z"):
            raise ToolError(f"Invalid column reference: {column_letters}")
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _column_index_to_letters(column_index: int) -> str:
    if column_index < 0:
        raise ToolError("Column index must be non-negative.")
    result = ""
    index = column_index + 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _header_row_values(spreadsheet_id: str, sheet_title: str, header_row: int = 1) -> list[str]:
    values = _sheets_service().spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_title}'!{header_row}:{header_row}",
    ).execute().get("values", [])
    return list(values[0]) if values else []


def _resolve_column_reference(
    spreadsheet_id: str,
    sheet_title: str,
    column_ref: str,
    *,
    header_row: int = 1,
) -> int:
    cleaned = column_ref.strip()
    if not cleaned:
        raise ToolError("Column reference cannot be empty.")
    if re.fullmatch(r"[A-Z]{1,4}", cleaned):
        return _column_index_from_letters(cleaned)
    headers = _header_row_values(spreadsheet_id, sheet_title, header_row=header_row)
    try:
        return headers.index(cleaned)
    except ValueError as exc:
        raise ToolError(f"Column '{cleaned}' was not found in header row {header_row}.") from exc


def _resolve_optional_column_reference(
    spreadsheet_id: str,
    sheet_title: str,
    column_ref: str,
    *,
    header_row: int = 1,
) -> int | None:
    try:
        return _resolve_column_reference(
            spreadsheet_id,
            sheet_title,
            column_ref,
            header_row=header_row,
        )
    except ToolError:
        return None


def _rows_to_records(values: list[list[Any]]) -> list[dict[str, Any]]:
    if not values:
        return []
    headers = [str(item).strip() for item in values[0]]
    records: list[dict[str, Any]] = []
    for row_offset, row in enumerate(values[1:], start=2):
        record: dict[str, Any] = {"_row": row_offset}
        for index, header in enumerate(headers):
            if not header:
                continue
            record[header] = row[index] if index < len(row) else ""
        records.append(record)
    return records


def _drive_permission(permission: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "type", "role", "emailAddress", "domain", "allowFileDiscovery")
    return {key: permission.get(key) for key in keys if key in permission}


def _list_permissions(file_id: str) -> list[dict[str, Any]]:
    response = _drive_service().permissions().list(
        fileId=file_id,
        supportsAllDrives=True,
        fields="permissions(id,type,role,emailAddress,domain,allowFileDiscovery)",
    ).execute()
    return [_drive_permission(permission) for permission in response.get("permissions", [])]


def _resolve_permission_id(file_id: str, permission_id: str = "", email_address: str = "") -> str:
    cleaned_permission_id = permission_id.strip()
    if cleaned_permission_id:
        return cleaned_permission_id

    cleaned_email = email_address.strip().lower()
    if not cleaned_email:
        raise ToolError("Either permission_id or email_address is required.")

    for permission in _list_permissions(file_id):
        if str(permission.get("emailAddress", "")).strip().lower() == cleaned_email:
            resolved = str(permission.get("id", "")).strip()
            if resolved:
                return resolved
    raise ToolError(f"No Drive permission found for {email_address!r}.")


def _sheet_preset_config(preset: str) -> dict[str, Any]:
    normalized = preset.strip().lower()
    presets: dict[str, dict[str, Any]] = {
        "ledger": {
            "freeze_rows": 1,
            "freeze_columns": 0,
            "currency_columns": [
                "Rate",
                "Amount",
                "Total",
                "Income",
                "Expenses",
                "Net Profit",
                "Balance",
                "Subtotal",
            ],
            "date_columns": ["Date", "Due Date", "Invoice Date", "Paid Date"],
        },
        "invoice": {
            "freeze_rows": 1,
            "freeze_columns": 0,
            "currency_columns": ["Rate", "Amount", "Subtotal", "Tax", "Total", "Balance Due"],
            "date_columns": ["Date", "Due Date", "Invoice Date"],
        },
        "inventory": {
            "freeze_rows": 1,
            "freeze_columns": 1,
            "currency_columns": ["Unit Cost", "Unit Price", "Total Cost", "Total Value", "Reorder Cost"],
            "date_columns": ["Date", "Last Updated", "Received Date", "Reorder Date"],
        },
        "bookings": {
            "freeze_rows": 1,
            "freeze_columns": 1,
            "currency_columns": ["Rate", "Amount", "Deposit", "Balance", "Total", "Refund"],
            "date_columns": ["Date", "Start Date", "End Date", "Booked Date", "Paid Date"],
        },
    }
    if normalized not in presets:
        raise ToolError(f"Unknown sheet preset '{preset}'. Supported presets: {', '.join(sorted(presets))}")
    return presets[normalized]


def _handle_error(action: str, exc: Exception) -> None:
    if isinstance(exc, ToolError):
        raise exc
    if isinstance(exc, GoogleWorkspaceConfigError):
        raise ToolError(str(exc)) from exc
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", "unknown")
        detail = exc.reason if getattr(exc, "reason", None) else str(exc)
        raise ToolError(f"{action} failed with Google API status {status}: {detail}") from exc
    raise ToolError(f"{action} failed: {exc}") from exc


@mcp.tool()
def search_drive_items(
    query: str,
    limit: int = 10,
    mime_type: str = "",
    parent_id: str = "",
    include_trashed: bool = False,
) -> dict[str, Any]:
    """Search Google Drive files and folders by name/full text.

    Args:
        query: Search text for file names or indexed content.
        limit: Maximum results to return (1-25).
        mime_type: Optional MIME type filter.
        parent_id: Optional Drive folder ID to scope the search.
        include_trashed: Include trashed files when true.
    """
    try:
        limit = max(1, min(limit, 25))
        filters: list[str] = []
        cleaned_query = query.strip()
        if cleaned_query:
            escaped = _escape_query(cleaned_query)
            filters.append(f"(name contains '{escaped}' or fullText contains '{escaped}')")
        if mime_type.strip():
            filters.append(f"mimeType = '{_escape_query(mime_type.strip())}'")
        if parent_id.strip():
            filters.append(f"'{_escape_query(parent_id.strip())}' in parents")
        if not include_trashed:
            filters.append("trashed = false")

        response = _drive_service().files().list(
            q=" and ".join(filters) if filters else None,
            pageSize=limit,
            fields="files(id,name,mimeType,webViewLink,modifiedTime,parents)",
            corpora="allDrives",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        return {"items": response.get("files", [])}
    except Exception as exc:
        _handle_error("Drive search", exc)


@mcp.tool()
def create_drive_folder(name: str, parent_id: str = "") -> dict[str, Any]:
    """Create a Google Drive folder.

    Args:
        name: Folder name.
        parent_id: Optional parent folder ID.
    """
    try:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ToolError("Folder name is required.")

        body: dict[str, Any] = {"name": cleaned_name, "mimeType": FOLDER_MIME}
        if parent_id.strip():
            body["parents"] = [parent_id.strip()]

        response = _drive_service().files().create(
            body=body,
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        response["action"] = "created"
        return response
    except Exception as exc:
        _handle_error("Drive folder create", exc)


@mcp.tool()
def move_drive_item(file_id: str, parent_id: str) -> dict[str, Any]:
    """Move an existing Drive item into a folder.

    Args:
        file_id: Drive item ID.
        parent_id: Destination folder ID.
    """
    try:
        cleaned_parent_id = parent_id.strip()
        if not cleaned_parent_id:
            raise ToolError("Destination parent_id is required.")
        _move_file_to_parent(file_id.strip(), cleaned_parent_id)
        metadata = _drive_item_metadata(file_id.strip())
        metadata["action"] = "moved"
        return metadata
    except Exception as exc:
        _handle_error("Drive move", exc)


@mcp.tool()
def rename_drive_item(file_id: str, name: str) -> dict[str, Any]:
    """Rename a Drive item.

    Args:
        file_id: Drive item ID.
        name: New item name.
    """
    try:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ToolError("New name is required.")
        response = _drive_service().files().update(
            fileId=file_id.strip(),
            body={"name": cleaned_name},
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        response["action"] = "renamed"
        return response
    except Exception as exc:
        _handle_error("Drive rename", exc)


@mcp.tool()
def delete_drive_item(file_id: str, permanent: bool = False) -> dict[str, Any]:
    """Trash or permanently delete a Drive item.

    Args:
        file_id: Drive item ID.
        permanent: Permanently delete when true. Otherwise move to trash.
    """
    try:
        cleaned_id = file_id.strip()
        metadata = _drive_item_metadata(cleaned_id)
        if permanent:
            _drive_service().files().delete(
                fileId=cleaned_id,
                supportsAllDrives=True,
            ).execute()
            metadata["action"] = "deleted"
            metadata["permanent"] = True
            return metadata

        response = _drive_service().files().update(
            fileId=cleaned_id,
            body={"trashed": True},
            fields="id,name,mimeType,webViewLink,modifiedTime,parents,trashed",
            supportsAllDrives=True,
        ).execute()
        response["action"] = "trashed"
        response["permanent"] = False
        return response
    except Exception as exc:
        _handle_error("Drive delete", exc)


@mcp.tool()
def ensure_drive_folder_path(folder_path: str, parent_id: str = "") -> dict[str, Any]:
    """Ensure that a slash-separated Drive folder path exists.

    Args:
        folder_path: Slash-separated folder path, e.g. `Receipts/2026/July`.
        parent_id: Optional starting parent folder ID.
    """
    try:
        existing, created = _ensure_folder_path(folder_path, parent_id)
        final_folder = (created or existing)[-1] if (created or existing) else None
        if final_folder is None:
            raise ToolError("folder_path must include at least one non-empty segment.")
        return {
            "folder": final_folder,
            "existing": existing,
            "created": created,
            "action": "ensured",
        }
    except Exception as exc:
        _handle_error("Drive folder path ensure", exc)


@mcp.tool()
def list_drive_folder_items(parent_id: str, recursive: bool = False, limit: int = 100) -> dict[str, Any]:
    """List the contents of a Drive folder.

    Args:
        parent_id: Folder ID to list.
        recursive: When true, recurse into child folders.
        limit: Maximum items to return.
    """
    try:
        cleaned_parent_id = parent_id.strip()
        if not cleaned_parent_id:
            raise ToolError("parent_id is required.")

        limit = max(1, min(limit, 500))
        results: list[dict[str, Any]] = []
        queue: list[tuple[str, str]] = [(cleaned_parent_id, "")]

        while queue and len(results) < limit:
            current_parent, prefix = queue.pop(0)
            query = (
                f"'{_escape_query(current_parent)}' in parents and trashed = false"
            )
            children = _drive_query(query=query, page_size=min(limit, 200))
            for child in children:
                child_copy = dict(child)
                child_copy["path"] = f"{prefix}/{child_copy.get('name', '')}".strip("/")
                results.append(child_copy)
                if recursive and child_copy.get("mimeType") == FOLDER_MIME and len(results) < limit:
                    queue.append((child_copy["id"], child_copy["path"]))
                if len(results) >= limit:
                    break

        return {"items": results, "recursive": recursive, "limit": limit}
    except Exception as exc:
        _handle_error("Drive folder list", exc)


@mcp.tool()
def read_drive_item(file_id: str, range_name: str = "") -> dict[str, Any]:
    """Read a Google Drive item as text or structured cell content.

    Args:
        file_id: Drive file ID, Google Doc ID, or Google Sheet ID.
        range_name: Optional Sheets range (for spreadsheet reads only).
    """
    try:
        metadata = _drive_service().files().get(
            fileId=file_id,
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        mime_type = metadata.get("mimeType", "")
        if mime_type == FOLDER_MIME:
            raise ToolError("Drive folders cannot be read as file content. Search inside the folder instead.")
        if mime_type == DOC_MIME:
            document = _docs_service().documents().get(documentId=file_id).execute()
            metadata["content"] = _extract_doc_text(document.get("body", {}).get("content", []))
            return metadata
        if mime_type == SHEET_MIME:
            resolved_range = range_name.strip() or _default_sheet_range(file_id)
            values = _sheets_service().spreadsheets().values().get(
                spreadsheetId=file_id,
                range=resolved_range,
            ).execute()
            metadata["range"] = values.get("range", resolved_range)
            metadata["values"] = values.get("values", [])
            return metadata
        if mime_type.startswith(TEXTUAL_MIME_PREFIXES) or mime_type in TEXTUAL_MIME_TYPES:
            metadata["content"] = _download_media(
                _drive_service().files().get_media(
                    fileId=file_id,
                    supportsAllDrives=True,
                ),
                mime_type,
            )
            return metadata
        raise ToolError(
            f"Drive item '{metadata.get('name', file_id)}' has unsupported MIME type '{mime_type}' for text reads."
        )
    except Exception as exc:
        _handle_error("Drive read", exc)


@mcp.tool()
def save_text_to_drive(
    name: str,
    content: str,
    parent_id: str = "",
    mime_type: str = "text/plain",
    overwrite_file_id: str = "",
) -> dict[str, Any]:
    """Create or overwrite a text-like file in Google Drive.

    Args:
        name: File name to create or set on update.
        content: UTF-8 text content to save.
        parent_id: Optional Drive folder ID for create operations.
        mime_type: MIME type for the uploaded file.
        overwrite_file_id: Existing Drive file ID to overwrite.
    """
    try:
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mime_type,
            resumable=False,
        )
        drive = _drive_service()
        if overwrite_file_id.strip():
            body: dict[str, Any] = {}
            if name.strip():
                body["name"] = name.strip()
            response = drive.files().update(
                fileId=overwrite_file_id.strip(),
                body=body or None,
                media_body=media,
                fields="id,name,mimeType,webViewLink,modifiedTime,parents",
                supportsAllDrives=True,
            ).execute()
            response["action"] = "updated"
            return response

        body = {"name": name.strip()}
        if parent_id.strip():
            body["parents"] = [parent_id.strip()]
        response = drive.files().create(
            body=body,
            media_body=media,
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        response["action"] = "created"
        return response
    except Exception as exc:
        _handle_error("Drive save", exc)


@mcp.tool()
def upload_file_to_drive(
    file_path: str,
    parent_id: str = "",
    name: str = "",
    mime_type: str = "",
    overwrite_file_id: str = "",
    convert_to_google_format: bool = False,
) -> dict[str, Any]:
    """Upload a local file to Google Drive without converting it to a Google-native type.

    Args:
        file_path: Local file path visible to the MCP process.
        parent_id: Optional destination folder ID for create operations.
        name: Optional Drive file name override.
        mime_type: Optional explicit MIME type. Defaults from the filename.
        overwrite_file_id: Existing Drive file ID to overwrite.
        convert_to_google_format: Convert supported Office/text files into Google-native types.
    """
    try:
        local_path = Path(file_path).expanduser()
        if not local_path.is_file():
            raise ToolError(f"Local file not found: {local_path}")

        resolved_name = name.strip() or local_path.name
        resolved_mime_type = _resolve_upload_mime_type(resolved_name, mime_type)
        google_target_mime = _resolve_google_conversion_target(local_path, convert_to_google_format)
        if convert_to_google_format and google_target_mime is None:
            raise ToolError(
                f"File type '{local_path.suffix or '(none)'}' cannot be converted to a Google-native format."
            )
        media = MediaFileUpload(
            str(local_path),
            mimetype=resolved_mime_type,
            resumable=False,
        )

        drive = _drive_service()
        if overwrite_file_id.strip():
            body: dict[str, Any] = {}
            if resolved_name:
                body["name"] = resolved_name
            if google_target_mime:
                body["mimeType"] = google_target_mime
            response = drive.files().update(
                fileId=overwrite_file_id.strip(),
                body=body or None,
                media_body=media,
                fields="id,name,mimeType,webViewLink,modifiedTime,parents",
                supportsAllDrives=True,
            ).execute()
            response["action"] = "updated"
        else:
            body = {"name": resolved_name}
            if google_target_mime:
                body["mimeType"] = google_target_mime
            if parent_id.strip():
                body["parents"] = [parent_id.strip()]
            response = drive.files().create(
                body=body,
                media_body=media,
                fields="id,name,mimeType,webViewLink,modifiedTime,parents",
                supportsAllDrives=True,
            ).execute()
            response["action"] = "created"

        response["sourcePath"] = str(local_path)
        response["convertedToGoogleType"] = google_target_mime
        return response
    except Exception as exc:
        _handle_error("Drive file upload", exc)


@mcp.tool()
def share_drive_item(
    file_id: str,
    email_address: str,
    role: str = "writer",
    send_notification_email: bool = False,
) -> dict[str, Any]:
    """Grant Google Drive access to a specific user.

    Args:
        file_id: Drive item ID.
        email_address: User email address.
        role: `reader`, `commenter`, `writer`, `fileOrganizer`, or `organizer`.
        send_notification_email: Ask Google to send the access email.
    """
    try:
        cleaned_email = email_address.strip()
        if not cleaned_email:
            raise ToolError("email_address is required.")
        allowed_roles = {"reader", "commenter", "writer", "fileOrganizer", "organizer"}
        if role not in allowed_roles:
            raise ToolError(f"role must be one of: {', '.join(sorted(allowed_roles))}")

        permission = _drive_service().permissions().create(
            fileId=file_id.strip(),
            body={"type": "user", "role": role, "emailAddress": cleaned_email},
            sendNotificationEmail=send_notification_email,
            supportsAllDrives=True,
            fields="id,type,role,emailAddress,domain,allowFileDiscovery",
        ).execute()
        return {
            "file": _drive_item_metadata(file_id.strip()),
            "permission": _drive_permission(permission),
            "action": "shared",
        }
    except Exception as exc:
        _handle_error("Drive share", exc)


@mcp.tool()
def create_drive_share_link(
    file_id: str,
    role: str = "reader",
    allow_file_discovery: bool = False,
) -> dict[str, Any]:
    """Create an anyone-with-link permission and return the Drive link.

    Args:
        file_id: Drive item ID.
        role: `reader`, `commenter`, or `writer`.
        allow_file_discovery: When true, make it discoverable to anyone in search.
    """
    try:
        if role not in {"reader", "commenter", "writer"}:
            raise ToolError("role must be one of: reader, commenter, writer")
        permission = _drive_service().permissions().create(
            fileId=file_id.strip(),
            body={
                "type": "anyone",
                "role": role,
                "allowFileDiscovery": allow_file_discovery,
            },
            supportsAllDrives=True,
            fields="id,type,role,allowFileDiscovery",
        ).execute()
        metadata = _drive_item_metadata(file_id.strip())
        return {
            "file": metadata,
            "permission": _drive_permission(permission),
            "shareLink": metadata.get("webViewLink"),
            "action": "link_shared",
        }
    except Exception as exc:
        _handle_error("Drive link share", exc)


@mcp.tool()
def list_drive_permissions(file_id: str) -> dict[str, Any]:
    """List the current Drive permissions on a file or folder."""
    try:
        cleaned_id = file_id.strip()
        if not cleaned_id:
            raise ToolError("file_id is required.")
        return {
            "file": _drive_item_metadata(cleaned_id),
            "permissions": _list_permissions(cleaned_id),
        }
    except Exception as exc:
        _handle_error("Drive permission list", exc)


@mcp.tool()
def revoke_drive_permission(
    file_id: str,
    permission_id: str = "",
    email_address: str = "",
) -> dict[str, Any]:
    """Remove a Drive permission by permission id or email address."""
    try:
        cleaned_id = file_id.strip()
        if not cleaned_id:
            raise ToolError("file_id is required.")
        resolved_permission_id = _resolve_permission_id(
            cleaned_id,
            permission_id=permission_id,
            email_address=email_address,
        )
        _drive_service().permissions().delete(
            fileId=cleaned_id,
            permissionId=resolved_permission_id,
            supportsAllDrives=True,
        ).execute()
        return {
            "file": _drive_item_metadata(cleaned_id),
            "revokedPermissionId": resolved_permission_id,
            "permissions": _list_permissions(cleaned_id),
            "action": "permission_revoked",
        }
    except Exception as exc:
        _handle_error("Drive permission revoke", exc)


@mcp.tool()
def update_drive_permission(
    file_id: str,
    role: str,
    permission_id: str = "",
    email_address: str = "",
    allow_file_discovery: bool | None = None,
) -> dict[str, Any]:
    """Update an existing Drive permission.

    Args:
        file_id: Drive item ID.
        role: New role (`reader`, `commenter`, `writer`, `fileOrganizer`, `organizer`).
        permission_id: Existing permission ID.
        email_address: Optional email address to resolve the permission when id is unknown.
        allow_file_discovery: Optional override for link-sharing discoverability.
    """
    try:
        cleaned_id = file_id.strip()
        if not cleaned_id:
            raise ToolError("file_id is required.")
        allowed_roles = {"reader", "commenter", "writer", "fileOrganizer", "organizer"}
        if role not in allowed_roles:
            raise ToolError(f"role must be one of: {', '.join(sorted(allowed_roles))}")

        resolved_permission_id = _resolve_permission_id(
            cleaned_id,
            permission_id=permission_id,
            email_address=email_address,
        )
        body: dict[str, Any] = {"role": role}
        if allow_file_discovery is not None:
            body["allowFileDiscovery"] = bool(allow_file_discovery)
        permission = _drive_service().permissions().update(
            fileId=cleaned_id,
            permissionId=resolved_permission_id,
            body=body,
            supportsAllDrives=True,
            fields="id,type,role,emailAddress,domain,allowFileDiscovery",
        ).execute()
        return {
            "file": _drive_item_metadata(cleaned_id),
            "permission": _drive_permission(permission),
            "permissions": _list_permissions(cleaned_id),
            "action": "permission_updated",
        }
    except Exception as exc:
        _handle_error("Drive permission update", exc)


@mcp.tool()
def copy_google_spreadsheet(
    spreadsheet_id: str,
    name: str = "",
    parent_id: str = "",
) -> dict[str, Any]:
    """Duplicate a whole Google Sheet file.

    Args:
        spreadsheet_id: Source spreadsheet id.
        name: Optional name override for the copy.
        parent_id: Optional destination folder id.
    """
    try:
        cleaned_id = spreadsheet_id.strip()
        if not cleaned_id:
            raise ToolError("spreadsheet_id is required.")
        source = _drive_item_metadata(cleaned_id)
        if source.get("mimeType") != SHEET_MIME:
            raise ToolError("copy_google_spreadsheet only supports Google Sheets.")
        body: dict[str, Any] = {}
        if name.strip():
            body["name"] = name.strip()
        copied = _drive_service().files().copy(
            fileId=cleaned_id,
            body=body or None,
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        if parent_id.strip():
            _move_file_to_parent(copied["id"], parent_id.strip())
            copied = _drive_item_metadata(copied["id"])
        copied["action"] = "spreadsheet_copied"
        copied["sourceSpreadsheetId"] = cleaned_id
        return copied
    except Exception as exc:
        _handle_error("Google Spreadsheet copy", exc)


@mcp.tool()
def export_drive_item(file_id: str, export_mime_type: str = "", output_path: str = "") -> dict[str, Any]:
    """Export a Google-native item to a local file.

    Args:
        file_id: Google Doc/Sheet/Slides file ID.
        export_mime_type: Target MIME type. Defaults to a sensible format for the source type.
        output_path: Optional local output path. Defaults to a temp file.
    """
    try:
        metadata = _drive_item_metadata(file_id.strip())
        source_mime = metadata.get("mimeType", "")
        if source_mime not in DEFAULT_EXPORT_MIME_BY_SOURCE:
            raise ToolError("Only Google-native Docs, Sheets, and Slides can be exported with this tool.")
        resolved_export_mime = export_mime_type.strip() or DEFAULT_EXPORT_MIME_BY_SOURCE[source_mime]
        suffix = EXPORT_EXTENSION_BY_MIME.get(resolved_export_mime, ".bin")
        if output_path.strip():
            destination = Path(output_path).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
        else:
            safe_name = metadata.get("name", "drive-item").replace("/", "_")
            destination = Path(tempfile.gettempdir()) / f"{safe_name}{suffix}"
        request = _drive_service().files().export_media(
            fileId=file_id.strip(),
            mimeType=resolved_export_mime,
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        destination.write_bytes(buffer.getvalue())
        return {
            "file": metadata,
            "exportMimeType": resolved_export_mime,
            "outputPath": str(destination),
            "action": "exported",
        }
    except Exception as exc:
        _handle_error("Drive export", exc)


@mcp.tool()
def create_google_doc(title: str, content: str = "", parent_id: str = "") -> dict[str, Any]:
    """Create a Google Doc and optionally seed it with content.

    Args:
        title: Document title.
        content: Optional initial document text.
        parent_id: Optional Drive folder ID to move the doc into.
    """
    try:
        document = _docs_service().documents().create(body={"title": title}).execute()
        document_id = document["documentId"]
        if parent_id.strip():
            _move_file_to_parent(document_id, parent_id)
        if content:
            _docs_service().documents().batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": content,
                            }
                        }
                    ]
                },
            ).execute()
        metadata = _drive_service().files().get(
            fileId=document_id,
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        metadata["content"] = content
        return metadata
    except Exception as exc:
        _handle_error("Google Doc create", exc)


@mcp.tool()
def read_google_doc(document_id: str) -> dict[str, Any]:
    """Read a Google Doc as plain text.

    Args:
        document_id: Google Doc ID.
    """
    try:
        metadata = _drive_service().files().get(
            fileId=document_id,
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        document = _docs_service().documents().get(documentId=document_id).execute()
        metadata["content"] = _extract_doc_text(document.get("body", {}).get("content", []))
        return metadata
    except Exception as exc:
        _handle_error("Google Doc read", exc)


@mcp.tool()
def update_google_doc(document_id: str, content: str, mode: str = "replace") -> dict[str, Any]:
    """Replace or append text in an existing Google Doc.

    Args:
        document_id: Google Doc ID.
        content: Text to write.
        mode: `replace` to replace the document body, `append` to append.
    """
    try:
        docs = _docs_service()
        document = docs.documents().get(documentId=document_id).execute()
        requests: list[dict[str, Any]] = []
        if mode == "replace":
            end_index = _doc_content_end_index(document)
            if end_index > 2:
                requests.append(
                    {
                        "deleteContentRange": {
                            "range": {"startIndex": 1, "endIndex": end_index - 1}
                        }
                    }
                )
            if content:
                requests.append(
                    {"insertText": {"location": {"index": 1}, "text": content}}
                )
        elif mode == "append":
            insert_at = max(1, _doc_content_end_index(document) - 1)
            if content:
                requests.append(
                    {"insertText": {"location": {"index": insert_at}, "text": content}}
                )
        else:
            raise ToolError("Google Doc update mode must be 'replace' or 'append'.")

        if requests:
            docs.documents().batchUpdate(
                documentId=document_id,
                body={"requests": requests},
            ).execute()
        return read_google_doc(document_id)
    except Exception as exc:
        _handle_error("Google Doc update", exc)


@mcp.tool()
def create_google_sheet(
    title: str,
    sheet_title: str = "",
    parent_id: str = "",
    values: list[list[str]] | None = None,
) -> dict[str, Any]:
    """Create a Google Sheet and optionally seed values into its first tab.

    Args:
        title: Spreadsheet title.
        sheet_title: Optional first sheet tab name.
        parent_id: Optional Drive folder ID to move the spreadsheet into.
        values: Optional values to write starting at A1.
    """
    try:
        body: dict[str, Any] = {"properties": {"title": title}}
        if sheet_title.strip():
            body["sheets"] = [{"properties": {"title": sheet_title.strip()}}]
        spreadsheet = _sheets_service().spreadsheets().create(body=body).execute()
        spreadsheet_id = spreadsheet["spreadsheetId"]
        if parent_id.strip():
            _move_file_to_parent(spreadsheet_id, parent_id)
        if values:
            target_tab = sheet_title.strip() or spreadsheet["sheets"][0]["properties"]["title"]
            _sheets_service().spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{target_tab}!A1",
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()
        return read_google_sheet(spreadsheet_id)
    except Exception as exc:
        _handle_error("Google Sheet create", exc)


@mcp.tool()
def list_google_sheet_tabs(spreadsheet_id: str) -> dict[str, Any]:
    """List the tabs in a Google Sheet.

    Args:
        spreadsheet_id: Google Sheet ID.
    """
    try:
        metadata = _drive_item_metadata(spreadsheet_id)
        metadata["tabs"] = _sheet_tabs(spreadsheet_id)
        return metadata
    except Exception as exc:
        _handle_error("Google Sheet tab list", exc)


@mcp.tool()
def add_google_sheet_tab(
    spreadsheet_id: str,
    sheet_title: str,
    index: int = -1,
) -> dict[str, Any]:
    """Add a new tab to an existing Google Sheet.

    Args:
        spreadsheet_id: Google Sheet ID.
        sheet_title: Title for the new tab.
        index: Optional zero-based sheet index. Use -1 to append.
    """
    try:
        cleaned_title = sheet_title.strip()
        if not cleaned_title:
            raise ToolError("sheet_title is required.")

        properties: dict[str, Any] = {"title": cleaned_title}
        if index >= 0:
            properties["index"] = index

        _sheets_service().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": properties}}]},
        ).execute()
        result = list_google_sheet_tabs(spreadsheet_id)
        result["action"] = "tab_added"
        return result
    except Exception as exc:
        _handle_error("Google Sheet tab create", exc)


@mcp.tool()
def rename_google_sheet_tab(spreadsheet_id: str, sheet_title: str, new_title: str) -> dict[str, Any]:
    """Rename an existing Google Sheet tab."""
    try:
        cleaned_new_title = new_title.strip()
        if not cleaned_new_title:
            raise ToolError("new_title is required.")
        sheet_id = _sheet_id_by_title(spreadsheet_id, sheet_title)
        _sheets_service().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_id, "title": cleaned_new_title},
                            "fields": "title",
                        }
                    }
                ]
            },
        ).execute()
        result = list_google_sheet_tabs(spreadsheet_id)
        result["action"] = "tab_renamed"
        return result
    except Exception as exc:
        _handle_error("Google Sheet tab rename", exc)


@mcp.tool()
def delete_google_sheet_tab(spreadsheet_id: str, sheet_title: str) -> dict[str, Any]:
    """Delete an existing Google Sheet tab."""
    try:
        sheet_id = _sheet_id_by_title(spreadsheet_id, sheet_title)
        _sheets_service().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        ).execute()
        result = list_google_sheet_tabs(spreadsheet_id)
        result["action"] = "tab_deleted"
        return result
    except Exception as exc:
        _handle_error("Google Sheet tab delete", exc)


@mcp.tool()
def copy_google_sheet_tab(
    spreadsheet_id: str,
    sheet_title: str,
    new_title: str = "",
    index: int = -1,
) -> dict[str, Any]:
    """Duplicate a tab within a Google Sheet."""
    try:
        source_sheet_id = _sheet_id_by_title(spreadsheet_id, sheet_title)
        response = _sheets_service().spreadsheets().sheets().copyTo(
            spreadsheetId=spreadsheet_id,
            sheetId=source_sheet_id,
            body={"destinationSpreadsheetId": spreadsheet_id},
        ).execute()
        copied_sheet_id = int(response["sheetId"])
        properties: dict[str, Any] = {"sheetId": copied_sheet_id}
        fields: list[str] = []
        if new_title.strip():
            properties["title"] = new_title.strip()
            fields.append("title")
        if index >= 0:
            properties["index"] = index
            fields.append("index")
        if fields:
            _sheets_service().spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": properties,
                                "fields": ",".join(fields),
                            }
                        }
                    ]
                },
            ).execute()
        result = list_google_sheet_tabs(spreadsheet_id)
        result["action"] = "tab_copied"
        result["copiedSheetId"] = copied_sheet_id
        return result
    except Exception as exc:
        _handle_error("Google Sheet tab copy", exc)


@mcp.tool()
def reorder_google_sheet_tab(spreadsheet_id: str, sheet_title: str, index: int) -> dict[str, Any]:
    """Move a Google Sheet tab to a new zero-based index."""
    try:
        if index < 0:
            raise ToolError("index must be zero or greater.")
        sheet_id = _sheet_id_by_title(spreadsheet_id, sheet_title)
        _sheets_service().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_id, "index": index},
                            "fields": "index",
                        }
                    }
                ]
            },
        ).execute()
        result = list_google_sheet_tabs(spreadsheet_id)
        result["action"] = "tab_reordered"
        return result
    except Exception as exc:
        _handle_error("Google Sheet tab reorder", exc)


@mcp.tool()
def read_google_sheet(spreadsheet_id: str, range_name: str = "") -> dict[str, Any]:
    """Read cells from a Google Sheet.

    Args:
        spreadsheet_id: Google Sheet ID.
        range_name: Optional A1 range. Defaults to the first tab.
    """
    try:
        metadata = _drive_service().files().get(
            fileId=spreadsheet_id,
            fields="id,name,mimeType,webViewLink,modifiedTime,parents",
            supportsAllDrives=True,
        ).execute()
        resolved_range = range_name.strip() or _default_sheet_range(spreadsheet_id)
        values = _sheets_service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=resolved_range,
        ).execute()
        metadata["range"] = values.get("range", resolved_range)
        metadata["values"] = values.get("values", [])
        return metadata
    except Exception as exc:
        _handle_error("Google Sheet read", exc)


@mcp.tool()
def update_google_sheet(
    spreadsheet_id: str,
    range_name: str,
    values: list[list[str]],
    mode: str = "replace",
) -> dict[str, Any]:
    """Replace or append values in a Google Sheet.

    Args:
        spreadsheet_id: Google Sheet ID.
        range_name: A1 range for the operation.
        values: Cell values to write.
        mode: `replace` to update the range, `append` to append rows.
    """
    try:
        sheets = _sheets_service().spreadsheets().values()
        if mode == "replace":
            sheets.update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()
        elif mode == "append":
            sheets.append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            ).execute()
        else:
            raise ToolError("Google Sheet update mode must be 'replace' or 'append'.")
        return read_google_sheet(spreadsheet_id, range_name)
    except Exception as exc:
        _handle_error("Google Sheet update", exc)


@mcp.tool()
def format_google_sheet_tab(
    spreadsheet_id: str,
    sheet_title: str,
    header_row: int = 1,
    bold_header: bool = True,
    freeze_rows: int = 1,
    freeze_columns: int = 0,
    currency_columns: list[str] | None = None,
    date_columns: list[str] | None = None,
    auto_resize_columns: bool = True,
) -> dict[str, Any]:
    """Apply common formatting to a Google Sheet tab."""
    try:
        tab = _sheet_tab_by_title(spreadsheet_id, sheet_title)
        sheet_id = int(tab["sheetId"])
        row_count = int(tab.get("rowCount") or 1000)
        column_count = int(tab.get("columnCount") or 26)
        data_end_row_index = row_count - 1 if row_count - 1 > header_row else row_count
        requests: list[dict[str, Any]] = []

        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {
                            "frozenRowCount": max(freeze_rows, 0),
                            "frozenColumnCount": max(freeze_columns, 0),
                        },
                    },
                    "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                }
            }
        )

        if bold_header:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": max(header_row - 1, 0),
                            "endRowIndex": header_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": column_count,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {"red": 0.92, "green": 0.95, "blue": 0.99},
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,backgroundColor)",
                    }
                }
            )

        for column_ref in currency_columns or []:
            column_index = _resolve_optional_column_reference(
                spreadsheet_id, sheet_title, column_ref, header_row=header_row
            )
            if column_index is None:
                continue
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": header_row,
                            "endRowIndex": data_end_row_index,
                            "startColumnIndex": column_index,
                            "endColumnIndex": column_index + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            )

        for column_ref in date_columns or []:
            column_index = _resolve_optional_column_reference(
                spreadsheet_id, sheet_title, column_ref, header_row=header_row
            )
            if column_index is None:
                continue
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": header_row,
                            "endRowIndex": data_end_row_index,
                            "startColumnIndex": column_index,
                            "endColumnIndex": column_index + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            )

        if auto_resize_columns:
            requests.append(
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": column_count,
                        }
                    }
                }
            )

        _sheets_service().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
        result = list_google_sheet_tabs(spreadsheet_id)
        result["action"] = "formatted"
        return result
    except Exception as exc:
        _handle_error("Google Sheet format", exc)


@mcp.tool()
def apply_google_sheet_preset(
    spreadsheet_id: str,
    sheet_title: str,
    preset: str,
    header_row: int = 1,
) -> dict[str, Any]:
    """Apply a named formatting preset to a Google Sheet tab.

    Supported presets:
    - `ledger`
    - `invoice`
    """
    try:
        config = _sheet_preset_config(preset)
        result = format_google_sheet_tab(
            spreadsheet_id=spreadsheet_id,
            sheet_title=sheet_title,
            header_row=header_row,
            bold_header=True,
            freeze_rows=config["freeze_rows"],
            freeze_columns=config["freeze_columns"],
            currency_columns=config["currency_columns"],
            date_columns=config["date_columns"],
            auto_resize_columns=True,
        )
        result["preset"] = preset.strip().lower()
        result["action"] = "preset_applied"
        return result
    except Exception as exc:
        _handle_error("Google Sheet preset apply", exc)


@mcp.tool()
def read_google_sheet_records(
    spreadsheet_id: str,
    sheet_title: str = "",
    range_name: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Read a Google Sheet tab as header-keyed records."""
    try:
        if range_name.strip():
            resolved_range = range_name.strip()
        else:
            resolved_sheet = sheet_title.strip() or _default_sheet_range(spreadsheet_id)
            resolved_range = f"'{resolved_sheet}'"
        values = _sheets_service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=resolved_range,
        ).execute()
        records = _rows_to_records(values.get("values", []))
        return {
            "spreadsheet": _drive_item_metadata(spreadsheet_id),
            "range": values.get("range", resolved_range),
            "records": records[: max(1, min(limit, 500))],
            "headers": list(values.get("values", [])[0]) if values.get("values") else [],
        }
    except Exception as exc:
        _handle_error("Google Sheet record read", exc)


@mcp.tool()
def append_google_sheet_records(
    spreadsheet_id: str,
    sheet_title: str,
    records: list[dict[str, Any]],
    create_headers_if_missing: bool = True,
) -> dict[str, Any]:
    """Append header-keyed records to a Google Sheet tab."""
    try:
        cleaned_sheet = sheet_title.strip() or _default_sheet_range(spreadsheet_id)
        if not records:
            raise ToolError("records must contain at least one item.")
        headers = _header_row_values(spreadsheet_id, cleaned_sheet)
        if not headers:
            if not create_headers_if_missing:
                raise ToolError("Target sheet has no header row.")
            headers = [str(key) for key in records[0].keys()]
            _sheets_service().spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{cleaned_sheet}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [headers]},
            ).execute()
        rows = [[record.get(header, "") for header in headers] for record in records]
        _sheets_service().spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"'{cleaned_sheet}'!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        result = read_google_sheet_records(spreadsheet_id, sheet_title=cleaned_sheet)
        result["action"] = "records_appended"
        result["appendedCount"] = len(rows)
        return result
    except Exception as exc:
        _handle_error("Google Sheet record append", exc)


@mcp.tool()
def update_google_sheet_record(
    spreadsheet_id: str,
    sheet_title: str,
    key_column: str,
    key_value: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update the first matching row in a Google Sheet tab by key-column value."""
    try:
        cleaned_sheet = sheet_title.strip() or _default_sheet_range(spreadsheet_id)
        if not updates:
            raise ToolError("updates must contain at least one field.")
        values = _sheets_service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{cleaned_sheet}'",
        ).execute().get("values", [])
        if not values:
            raise ToolError("Target sheet is empty.")
        headers = [str(item) for item in values[0]]
        key_index = _resolve_column_reference(spreadsheet_id, cleaned_sheet, key_column)
        if key_index >= len(headers):
            raise ToolError(f"Key column '{key_column}' is outside the header range.")

        target_row_number: int | None = None
        for row_number, row in enumerate(values[1:], start=2):
            cell_value = row[key_index] if key_index < len(row) else ""
            if str(cell_value) == key_value:
                target_row_number = row_number
                break
        if target_row_number is None:
            raise ToolError(f"No row found where {key_column} == {key_value!r}.")

        data = []
        for column_name, value in updates.items():
            try:
                column_index = headers.index(column_name)
            except ValueError as exc:
                raise ToolError(f"Column '{column_name}' was not found in the header row.") from exc
            a1_column = _column_index_to_letters(column_index)
            data.append(
                {
                    "range": f"'{cleaned_sheet}'!{a1_column}{target_row_number}",
                    "values": [[value]],
                }
            )

        _sheets_service().spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()
        result = read_google_sheet_records(spreadsheet_id, sheet_title=cleaned_sheet)
        result["action"] = "record_updated"
        result["row"] = target_row_number
        return result
    except Exception as exc:
        _handle_error("Google Sheet record update", exc)


if __name__ == "__main__":
    mcp.run(transport="stdio")