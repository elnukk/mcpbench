from fastmcp import FastMCP

mcp = FastMCP("dummy-users")


@mcp.tool()
def search_users(query: str) -> list[dict]:
    """Find users."""
    return [{"id": 1, "name": "John Doe", "email": "john@example.com"}]


@mcp.tool()
def filter_users(query: str) -> list[dict]:
    """Get users."""
    return [{"id": 1, "name": "John Doe", "email": "john@example.com"}]


@mcp.tool()
def lookup_user(query: str) -> list[dict]:
    """Look up a user."""
    return [{"id": 1, "name": "John Doe", "email": "john@example.com"}]
