"""Multi-view rendering pipeline.

Generates SVG (or other format) projections of a solved assembly from
standard engineering viewpoints: front, right, top, and isometric.
"""

from __future__ import annotations

import logging
from pathlib import Path

from forgeboard.assembly.orchestrator import SolvedAssembly
from forgeboard.core.types import Vector3
from forgeboard.engines.base import CadEngine, Shape

logger = logging.getLogger(__name__)

# Standard view directions.  Each maps a human-readable name to the
# direction vector the "camera" looks along (towards the origin).
VIEW_DIRECTIONS: dict[str, Vector3] = {
    "front": Vector3(x=0.0, y=-1.0, z=0.0),
    "back": Vector3(x=0.0, y=1.0, z=0.0),
    "right": Vector3(x=1.0, y=0.0, z=0.0),
    "left": Vector3(x=-1.0, y=0.0, z=0.0),
    "top": Vector3(x=0.0, y=0.0, z=-1.0),
    "bottom": Vector3(x=0.0, y=0.0, z=1.0),
    "isometric": Vector3(x=1.0, y=-1.0, z=1.0).normalized(),
    "iso": Vector3(x=1.0, y=-1.0, z=1.0).normalized(),
}

DEFAULT_VIEWS: list[str] = ["front", "right", "top", "isometric"]


def render_views(
    assembly: SolvedAssembly,
    output_dir: str,
    engine: CadEngine,
    views: list[str] | None = None,
    format: str = "svg",
) -> list[Path]:
    """Render orthographic / isometric views of a solved assembly.

    For each requested view, an SVG file is written to *output_dir* with the
    naming convention ``{assembly_name}_{view}.{format}``.

    Shapes inside the ``SolvedAssembly`` are already in world-space after
    solve, so no additional transforms are applied before rendering.

    Args:
        assembly: Fully solved assembly with positioned parts.
        output_dir: Directory to write rendered images into.
        engine: CAD engine instance used for boolean union and rendering.
        views: List of view names (see ``VIEW_DIRECTIONS``).  Defaults to
            ``["front", "right", "top", "isometric"]``.
        format: Output image format extension (default ``"svg"``).

    Returns:
        List of ``Path`` objects for each rendered file.

    Raises:
        ValueError: If the assembly has no parts or an unknown view is
            requested.
    """
    if not assembly.parts:
        raise ValueError("Cannot render an empty assembly.")

    if views is None:
        views = list(DEFAULT_VIEWS)

    # Validate view names early.
    unknown = [v for v in views if v not in VIEW_DIRECTIONS]
    if unknown:
        available = ", ".join(sorted(VIEW_DIRECTIONS))
        raise ValueError(
            f"Unknown view(s): {', '.join(unknown)}. "
            f"Available views: {available}"
        )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Collect world-space shapes from solved parts.
    shapes: list[Shape] = []
    for name, solved_part in assembly.parts.items():
        if solved_part.shape is None:
            logger.warning(
                "Part %r has no shape; skipping in render.", name
            )
            continue
        shapes.append(solved_part.shape)

    if not shapes:
        raise ValueError("No parts with shapes found; nothing to render.")

    # Fuse into a single compound for rendering.
    compound = shapes[0]
    for extra in shapes[1:]:
        compound = engine.boolean_union(compound, extra)
    compound.name = assembly.name

    # Sanitise assembly name for filenames.
    safe_name = (
        assembly.name.replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    output_paths: list[Path] = []
    for view_name in views:
        file_path = out / f"{safe_name}_{view_name}.{format}"
        engine.render_svg(compound, view_name, str(file_path))
        output_paths.append(file_path)
        logger.debug("Rendered view: %s -> %s", view_name, file_path)

    logger.info(
        "Render complete: %d views of %r in %s",
        len(output_paths),
        assembly.name,
        out,
    )
    return output_paths
