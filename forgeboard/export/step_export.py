"""STEP assembly export pipeline.

Builds a compound shape from all positioned parts in a solved assembly and
writes it to a STEP file via the CAD engine backend.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from forgeboard.assembly.orchestrator import SolvedAssembly
from forgeboard.engines.base import CadEngine, Shape

logger = logging.getLogger(__name__)


def export_assembly_step(
    assembly: SolvedAssembly,
    path: str,
    engine: CadEngine,
) -> Path:
    """Export a solved assembly to a single STEP file.

    The shapes inside a ``SolvedAssembly`` are already in world-space
    (transforms applied during solve), so this function simply collects
    them, fuses into a compound, attaches metadata, and writes the file.

    Args:
        assembly: Fully solved assembly with positioned parts.
        path: Destination file path for the STEP output.
        engine: CAD engine instance used for boolean union and export.

    Returns:
        Resolved ``Path`` of the written STEP file.

    Raises:
        ValueError: If the assembly contains no parts.
    """
    if not assembly.parts:
        raise ValueError("Cannot export an empty assembly to STEP.")

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Collect shapes -- they are already in world-space after solve().
    shapes: list[Shape] = []
    for name, solved_part in assembly.parts.items():
        if solved_part.shape is None:
            logger.warning(
                "Part %r has no shape attached; skipping in STEP export.",
                name,
            )
            continue
        shapes.append(solved_part.shape)

    if not shapes:
        raise ValueError(
            "No parts with shapes found in the assembly; nothing to export."
        )

    # Build metadata dict for the STEP header (stored in shape metadata).
    metadata: dict[str, object] = {
        "assembly_name": assembly.name,
        "part_count": len(shapes),
        "export_date": datetime.now(timezone.utc).isoformat(),
        "generator": "ForgeBoard",
    }
    metadata.update(assembly.metadata)

    # Fuse all shapes into a single compound.
    compound = shapes[0]
    for extra in shapes[1:]:
        compound = engine.boolean_union(compound, extra)

    compound.name = assembly.name
    compound.metadata.update(metadata)

    engine.export_step(compound, str(output))

    logger.info(
        "STEP export complete: %s (%d parts)", output, len(shapes)
    )
    return output
