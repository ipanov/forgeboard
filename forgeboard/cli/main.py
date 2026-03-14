"""ForgeBoard CLI -- Click-based command-line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import yaml

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
def serve() -> None:
    """Start the ForgeBoard MCP server.

    Launches a Model Context Protocol server via stdio that exposes
    ForgeBoard capabilities to AI coding agents (Claude Code, Cursor,
    Windsurf, etc.).
    """
    from forgeboard.mcp_server.runner import run_mcp_server

    run_mcp_server()


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


@main.command()
@click.option(
    "--image",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a sketch image (PNG, JPEG, etc.).",
)
@click.option(
    "--description",
    "-d",
    default="",
    help="Text description of the design (used alone or with --image).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file for ComponentSpecs YAML.  Defaults to stdout.",
)
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "mock"], case_sensitive=False),
    default="anthropic",
    show_default=True,
    help="LLM provider to use for analysis.",
)
@click.option(
    "--no-wizard",
    is_flag=True,
    default=False,
    help="Skip the interactive wizard and output analysis only.",
)
def sketch(
    image: Path | None,
    description: str,
    output: Path | None,
    provider: str,
    no_wizard: bool,
) -> None:
    """Analyze a sketch or text description and generate ComponentSpecs.

    Reads a sketch image and/or text description, analyzes them to extract
    design intent, then runs an interactive wizard to fill in missing
    details.  Outputs the resulting ComponentSpecs as YAML.

    \b
    Examples:
      forgeboard sketch --image sketch.png
      forgeboard sketch --image sketch.png -d "motor bracket, 3mm aluminum"
      forgeboard sketch -d "L-bracket for NEMA 17, 6061 aluminum"
      forgeboard sketch --image sketch.png --no-wizard
    """
    if image is None and not description.strip():
        raise click.UsageError(
            "At least one of --image or --description is required."
        )

    from forgeboard.design.analyzer import DesignAnalyzer
    from forgeboard.design.wizard import DesignWizard

    llm = _create_provider(provider)

    click.echo("[forgeboard sketch] Analyzing design input...")
    if image:
        click.echo(f"  Image: {image}")
    if description:
        click.echo(f"  Description: {description}")
    click.echo()

    # -- Analysis ----------------------------------------------------------
    analyzer = DesignAnalyzer(llm)
    image_str = str(image) if image else None
    analysis = analyzer.analyze_combined(image_str, description)

    click.echo(f"  Components found: {len(analysis.components)}")
    for comp in analysis.components:
        cots_tag = " [COTS]" if comp.is_cots_candidate else ""
        click.echo(f"    - {comp.name}{cots_tag} (confidence: {comp.confidence:.0%})")
    click.echo(f"  Completeness: {analysis.completeness_score:.0%}")
    click.echo(f"  Missing details: {len(analysis.missing_details)}")
    for detail in analysis.missing_details:
        click.echo(f"    - {detail}")
    click.echo()

    # -- Wizard (interactive) ----------------------------------------------
    if no_wizard or not analysis.missing_details:
        if not analysis.missing_details:
            click.echo("  Design is complete -- no wizard needed.")
        else:
            click.echo("  Wizard skipped (--no-wizard).")
        click.echo()

        wizard = DesignWizard(llm)
        session = wizard.start_session(analysis)
        session.is_complete = True
        specs = wizard.finalize(session)
    else:
        click.echo("  Starting interactive wizard...")
        click.echo("  (Answer questions to fill in missing details.)")
        click.echo()

        wizard = DesignWizard(llm)
        session = wizard.start_session(analysis)

        while not session.is_complete:
            question = wizard.next_question(session)
            if question is None:
                break

            # Display the question.
            click.echo(f"  Q: {question.text}")
            if question.context:
                click.echo(f"     ({question.context})")

            if question.options:
                for i, opt in enumerate(question.options, 1):
                    click.echo(f"     {i}. {opt}")
                raw = click.prompt("  Your answer (number or text)", type=str)

                # If user typed a number, map to the option.
                try:
                    idx = int(raw.strip()) - 1
                    if 0 <= idx < len(question.options):
                        answer = question.options[idx]
                    else:
                        answer = raw.strip()
                except ValueError:
                    answer = raw.strip()
            else:
                answer = click.prompt("  Your answer", type=str)

            session = wizard.answer(session, question.id, answer)
            click.echo()

        specs = wizard.finalize(session)

    # -- Output ------------------------------------------------------------
    click.echo(f"  Generated {len(specs)} ComponentSpec(s).")
    click.echo()

    specs_data = [spec.model_dump(exclude_none=True) for spec in specs]
    yaml_output = yaml.dump(specs_data, sort_keys=False, default_flow_style=False)

    if output:
        output.write_text(yaml_output, encoding="utf-8")
        click.echo(f"  Saved to: {output}")
    else:
        click.echo(yaml_output)


def _create_provider(name: str) -> Any:
    """Create an LLM provider by name."""
    if name == "mock":
        from forgeboard.design.llm_provider import MockProvider
        return MockProvider()
    elif name == "anthropic":
        from forgeboard.design.llm_provider import AnthropicProvider
        try:
            return AnthropicProvider()
        except (ImportError, ValueError) as exc:
            raise click.ClickException(
                f"Cannot initialize Anthropic provider: {exc}\n"
                "Set ANTHROPIC_API_KEY or use --provider mock for testing."
            ) from exc
    else:
        raise click.ClickException(f"Unknown provider: {name}")


if __name__ == "__main__":
    main()
