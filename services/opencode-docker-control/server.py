import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from controller_logic import ControlError, manage_service as run_service_action


mcp = FastMCP(
    "Qacey Docker Control",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
    instructions=(
        "Manage approved services from docker-compose.platform.yml. Every operation requires "
        "user approval. Never attempt a broader Docker operation."
    ),
)


@mcp.tool()
def manage_service(
    action: Literal["status", "logs", "start", "stop", "restart", "build", "up"],
    service: str,
) -> str:
    """Run one approved Qacey Compose operation on one service.

    Actions are status, logs, start, stop, restart, build, and up. The up action
    rebuilds and recreates only the selected service, without dependencies.
    """
    try:
        return run_service_action(action, service)
    except ControlError as exc:
        raise ToolError(str(exc)) from exc


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
