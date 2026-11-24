from __future__ import annotations

import logging
import os
from typing import Any


logger = logging.getLogger(__name__)


def _is_openrouter_base_url(base_url: Any) -> bool:
    value = str(base_url or "").strip().lower()
    return value.startswith("https://openrouter.ai/") or value == "https://openrouter.ai"


def _resolve_openrouter_session_id(params: Any) -> str | None:
    candidate = None
    if isinstance(params, dict):
        candidate = params.get("session_id")
    if candidate is None:
        candidate = os.getenv("HERMES_SESSION_ID")
    value = str(candidate or "").strip()
    return value or None


def _inject_openrouter_session_id(api_kwargs: Any, params: Any) -> None:
    if not isinstance(api_kwargs, dict):
        return
    if not _is_openrouter_base_url((params or {}).get("base_url") if isinstance(params, dict) else None):
        return

    session_id = _resolve_openrouter_session_id(params)
    if not session_id:
        return

    extra_body = api_kwargs.get("extra_body")
    if extra_body is None:
        api_kwargs["extra_body"] = {"session_id": session_id}
        return
    if isinstance(extra_body, dict):
        extra_body.setdefault("session_id", session_id)


def _patch_openrouter_session_id() -> None:
    try:
        from agent.transports.chat_completions import ChatCompletionsTransport
    except Exception:
        logger.debug("OpenRouter session_id patch skipped: chat transport unavailable", exc_info=True)
        return

    transport_cls = ChatCompletionsTransport
    if getattr(transport_cls, "_qacey_openrouter_session_patch_applied", False):
        return

    original_build_kwargs = transport_cls.build_kwargs

    def patched_build_kwargs(
        self: Any,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        api_kwargs = original_build_kwargs(self, model, messages, tools, **params)
        _inject_openrouter_session_id(api_kwargs, params)
        return api_kwargs

    transport_cls.build_kwargs = patched_build_kwargs
    transport_cls._qacey_openrouter_session_patch_applied = True
    transport_cls._qacey_original_build_kwargs = original_build_kwargs
    logger.info("Applied Qacey OpenRouter session_id patch")


_patch_openrouter_session_id()