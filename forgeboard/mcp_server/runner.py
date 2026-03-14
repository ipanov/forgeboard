"""Entry point for running ForgeBoard as an MCP server.

This module provides the ``run_mcp_server`` function that starts the
ForgeBoard MCP server using stdio transport.  It is called by the CLI
``forgeboard serve`` command and by the ``forgeboard`` entry point
in pyproject.toml.
"""

from __future__ import annotations


def run_mcp_server() -> None:
    """Run ForgeBoard as an MCP server via stdio.

    This starts the FastMCP server with stdio transport, which is the
    standard way for AI assistants (Claude Code, Cursor, Windsurf) to
    communicate with MCP servers.
    """
    # Import tools module to register all @mcp.tool() decorators
    import forgeboard.mcp_server.tools  # noqa: F401
    from forgeboard.mcp_server.server import mcp

    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
