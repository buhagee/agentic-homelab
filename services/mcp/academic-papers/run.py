# run.py — streamable-http wrapper for paper-search-mcp
# paper_search_mcp.server only exposes stdio transport natively.
# FastMCP supports streamable-http; we import the pre-built mcp
# instance (all tools already registered) and re-run it with that transport.
import os

from paper_search_mcp.server import mcp  # noqa: F401 — tools registered on import

# Patch host/port so the server binds on all interfaces inside Docker
mcp.settings.host = os.environ.get("FASTMCP_HOST", "0.0.0.0")
mcp.settings.port = int(os.environ.get("FASTMCP_PORT", "8000"))

# Disable DNS rebinding protection so requests from other Docker containers
# (addressed by hostname) are accepted
if mcp.settings.transport_security is not None:
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

mcp.run(transport="streamable-http")
