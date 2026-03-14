"""Model Context Protocol server for AI agent integration.

This package exposes the ForgeBoard Python API as MCP tools, enabling
AI assistants (Claude Code, Cursor, Windsurf, etc.) to create CAD
components, build assemblies, run validation, and generate BOMs through
structured tool calls.

Usage:
    forgeboard serve        # Start MCP server via CLI
    run_mcp_server()        # Start MCP server programmatically
"""

from forgeboard.mcp_server.runner import run_mcp_server
from forgeboard.mcp_server.server import mcp

__all__ = ["mcp", "run_mcp_server"]
