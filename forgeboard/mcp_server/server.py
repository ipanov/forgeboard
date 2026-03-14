"""ForgeBoard MCP server.

Exposes the ForgeBoard Python API as MCP tools so that AI assistants
(Claude Code, Cursor, Windsurf, etc.) can create components, build
assemblies, run validation, and generate BOMs through structured tool
calls.

The server is STATEFUL: it maintains a ForgeProject instance across
tool calls within a session.  This is intentional -- the AI builds up
an assembly incrementally over multiple calls.

Architecture: the MCP server contains NO business logic.  Every tool
delegates to the existing ForgeBoard Python API.  All logic lives in
the library (deterministic, testable).  The MCP layer just marshals
inputs and outputs.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from forgeboard.core.project import ForgeProject

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "forgeboard",
    instructions=(
        "ForgeBoard is an AI-driven CAD assembly orchestration engine. "
        "Use these tools to create components, build assemblies, run "
        "validation and collision detection, generate bills of materials, "
        "and export STEP/STL files.  The server maintains project state "
        "across tool calls -- create a project first, then add components "
        "and assemblies incrementally."
    ),
)

# ---------------------------------------------------------------------------
# Global project state (persists across tool calls within a session)
# ---------------------------------------------------------------------------

_project: ForgeProject | None = None


def get_project() -> ForgeProject:
    """Return the current project, raising if none exists."""
    if _project is None:
        raise RuntimeError(
            "No project has been created yet. "
            "Call forgeboard_create_project first."
        )
    return _project


def set_project(project: ForgeProject) -> None:
    """Set the global project instance."""
    global _project
    _project = project


def reset_project() -> None:
    """Clear the global project instance."""
    global _project
    _project = None
