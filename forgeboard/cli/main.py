"""ForgeBoard CLI -- Click-based command-line interface."""

from __future__ import annotations

from pathlib import Path

import click

from forgeboard import __version__


@click.group()
@click.version_option(version=__version__, prog_name="forgeboard")
def main() -> None:
    """ForgeBoard -- AI-driven CAD assembly orchestration engine."""


@main.command()
@click.argument("description")
def design(description: str) -> None:
    """Generate CAD components from a natural-language description.

    DESCRIPTION is a text prompt describing the part to create.
    """
    click.echo(f"[forgeboard design] Generating component from description:")
    click.echo(f"  \"{description}\"")
    click.echo()
    click.echo("  Engine:  build123d")
    click.echo("  Status:  not yet implemented")


@main.command()
@click.option(
    "--registry",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the assembly registry YAML file.",
)
def assemble(registry: Path) -> None:
    """Assemble components from a registry file.

    Reads component definitions and constraints from a YAML registry,
    solves constraints, and produces an assembled output.
    """
    click.echo(f"[forgeboard assemble] Building assembly from registry:")
    click.echo(f"  Registry: {registry}")
    click.echo()
    click.echo("  Steps:")
    click.echo("    1. Parse registry")
    click.echo("    2. Load components")
    click.echo("    3. Solve constraints")
    click.echo("    4. Check collisions")
    click.echo("    5. Export assembly")
    click.echo()
    click.echo("  Status: not yet implemented")


@main.command()
@click.option(
    "--assembly",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the assembly STEP file to validate.",
)
def validate(assembly: Path) -> None:
    """Run the validation pipeline on an assembly.

    Checks constraint satisfaction, interference/collision between
    components, and dimensional consistency.
    """
    click.echo(f"[forgeboard validate] Validating assembly:")
    click.echo(f"  File: {assembly}")
    click.echo()
    click.echo("  Checks:")
    click.echo("    - Constraint satisfaction")
    click.echo("    - Collision / interference detection")
    click.echo("    - Dimensional consistency")
    click.echo("    - Material assignments")
    click.echo()
    click.echo("  Status: not yet implemented")


@main.command()
@click.option(
    "--assembly",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the assembly STEP file.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json", "yaml"], case_sensitive=False),
    default="csv",
    show_default=True,
    help="Output format for the BOM.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path. Defaults to stdout.",
)
def bom(assembly: Path, output_format: str, output: Path | None) -> None:
    """Generate a bill of materials from an assembly.

    Extracts component names, quantities, materials, masses, and
    sourcing information.
    """
    dest = str(output) if output else "stdout"
    click.echo(f"[forgeboard bom] Generating bill of materials:")
    click.echo(f"  Assembly: {assembly}")
    click.echo(f"  Format:   {output_format}")
    click.echo(f"  Output:   {dest}")
    click.echo()
    click.echo("  Status: not yet implemented")


@main.command()
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host to bind the MCP server to.",
)
@click.option(
    "--port",
    default=8370,
    show_default=True,
    type=int,
    help="Port to bind the MCP server to.",
)
def serve(host: str, port: int) -> None:
    """Start the ForgeBoard MCP server.

    Launches a Model Context Protocol server that exposes ForgeBoard
    capabilities to AI coding agents.
    """
    click.echo(f"[forgeboard serve] Starting MCP server:")
    click.echo(f"  Host: {host}")
    click.echo(f"  Port: {port}")
    click.echo()
    click.echo("  Status: not yet implemented")


@main.command()
@click.option(
    "--assembly",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the assembly STEP file to render.",
)
@click.option(
    "--views",
    default="front,right,top,iso",
    show_default=True,
    help="Comma-separated list of views to render.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("renders"),
    show_default=True,
    help="Directory to save rendered images.",
)
def render(assembly: Path, views: str, output_dir: Path) -> None:
    """Render orthographic and isometric views of an assembly.

    Generates PNG images for each requested view angle.
    """
    view_list = [v.strip() for v in views.split(",")]
    click.echo(f"[forgeboard render] Rendering assembly views:")
    click.echo(f"  Assembly:   {assembly}")
    click.echo(f"  Views:      {', '.join(view_list)}")
    click.echo(f"  Output dir: {output_dir}")
    click.echo()
    click.echo("  Status: not yet implemented")


if __name__ == "__main__":
    main()
