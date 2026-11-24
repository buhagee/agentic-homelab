"""
Custom entry point for the intervals-mcp-server that reads the API key from
the incoming HTTP 'Authorization' header on every request, rather than
requiring API_KEY to be set as an environment variable at startup.

This allows a single shared container to serve multiple users — each user's
LIA account sends their personal API key as the Authorization header when the
MCP client connects, so each tool call runs with their credentials.

Middleware flow:
    HTTP POST /mcp
      → APIKeyMiddleware extracts 'Authorization' header
      → stores value in _request_api_key contextvar
      → FastMCP dispatches tool call
      → tool calls get_config() which checks contextvar first, falls back
        to API_KEY env var (for local dev or single-user deployments)
"""

import contextvars
import os

import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Per-request contextvar for the API key extracted from Authorization header
# ---------------------------------------------------------------------------
_request_api_key: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_request_api_key", default=""
)

# ---------------------------------------------------------------------------
# Patch intervals_mcp_server.config.get_config to check contextvar first
# ---------------------------------------------------------------------------
import intervals_mcp_server.config as _cfg  # noqa: E402

_orig_load_config = _cfg.load_config


def _patched_get_config() -> _cfg.Config:  # type: ignore[return]
    """Return config, overriding api_key from per-request contextvar if set."""
    key_from_header = _request_api_key.get("")
    if key_from_header:
        # Use a fresh Config with the header-supplied key; derive other fields
        # from the env-var-based singleton so ATHLETE_ID etc. are still honoured.
        base = _orig_load_config()
        return _cfg.Config(
            api_key=key_from_header,
            athlete_id=base.athlete_id,
            intervals_api_base_url=base.intervals_api_base_url,
            user_agent=base.user_agent,
        )
    # Fall back to the env-var singleton (single-user / local dev mode)
    if _cfg._config_instance is None:
        _cfg._config_instance = _orig_load_config()
    return _cfg._config_instance


_cfg.get_config = _patched_get_config


# ---------------------------------------------------------------------------
# Starlette middleware: extract API key from Authorization header
# ---------------------------------------------------------------------------
class APIKeyMiddleware(BaseHTTPMiddleware):
    """Extract the Authorization header value and expose it via contextvar."""

    async def dispatch(self, request: Request, call_next) -> Response:
        auth = request.headers.get("Authorization", "")
        token = _request_api_key.set(auth)
        try:
            return await call_next(request)
        finally:
            _request_api_key.reset(token)


# ---------------------------------------------------------------------------
# Build the Starlette app and inject middleware
# ---------------------------------------------------------------------------
# Import AFTER patching config so tools see the patched get_config
from intervals_mcp_server.mcp_instance import mcp  # noqa: E402

# Import server module so that all @mcp.tool() decorators execute and register
# the 17 tools on the shared `mcp` instance BEFORE the Starlette app is built.
# Without this import, mcp_instance only creates the FastMCP object — no tools.
import intervals_mcp_server.server  # noqa: F401, E402

app = mcp.streamable_http_app()
app.add_middleware(APIKeyMiddleware)

# ---------------------------------------------------------------------------
# Run with uvicorn
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
