"""STL export pipeline for assemblies and individual parts.

Provides both whole-assembly export (single STL) and per-part export
(one STL file per component, suitable for 3D printing).
"""

from __future__ import annotations

import logging
from pathlib import Path

from forgeboard.assembly.orchestrator import SolvedAssembly
from forgeboard.engines.base import CadEngine, Shape

logger = logging.getLogger(__name__)


def export_assembly_stl(
    assembly: SolvedAssembly,
    path: str,
    engine: CadEngine,
) -> Path:
    """Export the full assembly as a single STL mesh.

    Shapes in a ``SolvedAssembly`` are already in world-space after the
    constraint solver has run, so no additional transforms are applied.

    Args:
        assembly: Fully solved assembly with positioned parts.
        path: Destination file path for the STL output.
        engine: CAD engine instance used for boolean union and export.

    Returns:
        Resolved ``Path`` of the written STL file.

    Raises:
        ValueError: If the assembly contains no exportable parts.
    """
    if not assembly.parts:
        raise ValueError("Cannot export an empty assembly to STL.")

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    shapes: list[Shape] = []
    for name, solved_part in assembly.parts.items():
        if solved_part.shape is None:
            logger.warning(
                "Part %r has no shape; skipping in STL export.", name
            )
            continue
        shapes.append(solved_part.shape)

    if not shapes:
        raise ValueError(
            "No parts with shapes found in the assembly; nothing to export."
        )

    # Build compound via iterative union.
    compound = shapes[0]
    for extra in shapes[1:]:
        compound = engine.boolean_union(compound, extra)

    compound.name = assembly.name
    engine.export_stl(compound, str(output))

    logger.info(
        "STL assembly export complete: %s (%d parts)",
        output,
        len(shapes),
    )
    return output


def export_parts_stl(
    assembly: SolvedAssembly,
    output_dir: str,
    engine: CadEngine,
) -> list[Path]:
    """Export each part in the assembly as an individual STL file.

    File names are derived from the part name with a ``.stl`` suffix.
    Parts without shapes are silently skipped.

    Args:
        assembly: Fully solved assembly with positioned parts.
        output_dir: Directory to write individual STL files into.
        engine: CAD engine instance used for export.

    Returns:
        List of ``Path`` objects for each successfully written STL file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for name, solved_part in assembly.parts.items():
        if solved_part.shape is None:
            logger.warning(
                "Part %r has no shape; skipping in per-part STL export.", name
            )
            continue

        # Sanitise the part name for use as a filename.
        safe_name = (
            name.replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
        stl_path = out / f"{safe_name}.stl"
        engine.export_stl(solved_part.shape, str(stl_path))
        paths.append(stl_path)

        logger.debug("Exported part STL: %s", stl_path)

    logger.info(
        "Per-part STL export complete: %d files in %s", len(paths), out
    )
    return paths
