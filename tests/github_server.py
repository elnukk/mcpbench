import os
from fastmcp.client.transports import StdioTransport

token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
if not token:
    raise EnvironmentError(
        "Set GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN before running."
    )


def make_transport() -> StdioTransport:
    """A fresh StdioTransport per scenario.

    Reusing one StdioTransport instance across multiple connect/disconnect
    cycles can leave it permanently broken if a connection ever ends on an
    error (some fastmcp/mcp versions don't reset the transport's internal
    connect-task state in that case), so each scenario gets its own.
    """
    return StdioTransport(
        command="github-mcp-server",
        args=["stdio"],
        env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token},
        keep_alive=False,
    )
