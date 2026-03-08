import os
from fastmcp.client.transports import StdioTransport

token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
if not token:
    raise EnvironmentError(
        "Set GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN before running."
    )

transport = StdioTransport(
    command="github-mcp-server",
    args=["stdio"],
    env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token},
    keep_alive=False,
)
