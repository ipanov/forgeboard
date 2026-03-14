"""Collision detection and clearance verification for assemblies.

Provides two main entry points:

- :func:`check_pairwise_collisions` -- detects physical overlaps between all
  part pairs using AABB pre-filtering and exact boolean intersection.
- :func:`check_clearance` -- verifies that minimum air gaps are maintained
  between parts (useful for thermal, electrical, or manufacturing tolerances).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import TYPE_CHECKING

from forgeboard.core.types import BoundingBox

if TYPE_CHECKING:
    from forgeboard.engines.base import CadEngine, Shape


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

class CollisionSeverity(Enum):
    """Severity bucket for a detected collision.

    Thresholds (in mm^3 of intersection volume):
        MINOR    :  0 < volume < 10
        MAJOR    : 10 <= volume < 100
        CRITICAL : volume >= 100
    """

    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


def _classify_severity(volume_mm3: float) -> CollisionSeverity:
    if volume_mm3 >= 100.0:
        return CollisionSeverity.CRITICAL
    if volume_mm3 >= 10.0:
        return CollisionSeverity.MAJOR
    return CollisionSeverity.MINOR


# ---------------------------------------------------------------------------
# Collision result
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Collision:
    """A detected physical overlap between two parts.

    Attributes
    ----------
    part_a : str
        Name of the first part.
    part_b : str
        Name of the second part.
    volume_mm3 : float
        Volume of the intersection in cubic millimetres.
    severity : CollisionSeverity
        Classified severity of the collision.
    """

    part_a: str
    part_b: str
    volume_mm3: float
    severity: CollisionSeverity


# ---------------------------------------------------------------------------
# Clearance violation
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ClearanceViolation:
    """A pair of parts that are closer than the required minimum gap.

    Attributes
    ----------
    part_a : str
        Name of the first part.
    part_b : str
        Name of the second part.
    actual_gap_mm : float
        Measured minimum gap (negative means overlapping).
    required_gap_mm : float
        The required minimum clearance.
    """

    part_a: str
    part_b: str
    actual_gap_mm: float
    required_gap_mm: float


# ---------------------------------------------------------------------------
# AABB helpers
# ---------------------------------------------------------------------------

def _aabb_overlap(a: BoundingBox, b: BoundingBox, margin: float = 0.0) -> bool:
    """Return True if the two AABBs overlap (expanded by *margin*)."""
    return a.overlaps(b, margin=margin)


def _aabb_min_gap(a: BoundingBox, b: BoundingBox) -> float:
    """Estimate the minimum gap between two AABBs.

    Returns a negative value when the boxes overlap.  This is a conservative
    (over-)estimate -- the actual gap between curved surfaces may be larger.
    """
    dx = max(a.x_min - b.x_max, b.x_min - a.x_max, 0.0)
    dy = max(a.y_min - b.y_max, b.y_min - a.y_max, 0.0)
    dz = max(a.z_min - b.z_max, b.z_min - a.z_max, 0.0)

    # If all separations are zero the boxes touch or overlap
    if dx == 0.0 and dy == 0.0 and dz == 0.0:
        # Compute overlap depth on each axis; take the smallest as the
        # penetration (negative gap).
        overlap_x = min(a.x_max, b.x_max) - max(a.x_min, b.x_min)
        overlap_y = min(a.y_max, b.y_max) - max(a.y_min, b.y_min)
        overlap_z = min(a.z_max, b.z_max) - max(a.z_min, b.z_min)
        return -min(overlap_x, overlap_y, overlap_z)

    # The L-infinity separation (conservative minimum gap)
    return max(dx, dy, dz)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_pairwise_collisions(
    parts: dict[str, Shape],
    engine: CadEngine,
    tolerance_mm3: float = 1.0,
) -> list[Collision]:
    """Check every pair of parts for physical overlap.

    Uses AABB pre-filtering to skip pairs whose bounding boxes do not
    overlap, then falls back to exact boolean intersection for the
    remaining candidates.

    Parameters
    ----------
    parts : dict[str, Shape]
        Mapping of part name to engine Shape.
    engine : CadEngine
        The CAD engine to use for geometric operations.
    tolerance_mm3 : float
        Intersection volumes below this threshold are ignored.

    Returns
    -------
    list[Collision]
        One entry for every pair that collides, sorted by severity
        (CRITICAL first).
    """
    if len(parts) < 2:
        return []

    # Pre-compute bounding boxes
    bboxes: dict[str, BoundingBox] = {}
    for name, shape in parts.items():
        try:
            bboxes[name] = engine.measure_bounding_box(shape)
        except Exception:
            # If bounding-box measurement fails, skip this part rather than
            # aborting the entire pipeline.
            continue

    collisions: list[Collision] = []
    for name_a, name_b in combinations(parts, 2):
        # AABB pre-check
        bb_a = bboxes.get(name_a)
        bb_b = bboxes.get(name_b)
        if bb_a is None or bb_b is None:
            continue
        if not _aabb_overlap(bb_a, bb_b):
            continue

        # Exact check via boolean intersection
        result = engine.check_collision(parts[name_a], parts[name_b])
        if result.has_collision and result.volume_mm3 >= tolerance_mm3:
            collisions.append(
                Collision(
                    part_a=name_a,
                    part_b=name_b,
                    volume_mm3=result.volume_mm3,
                    severity=_classify_severity(result.volume_mm3),
                )
            )

    # Sort: CRITICAL first, then MAJOR, then MINOR; within each tier by
    # descending volume.
    severity_order = {
        CollisionSeverity.CRITICAL: 0,
        CollisionSeverity.MAJOR: 1,
        CollisionSeverity.MINOR: 2,
    }
    collisions.sort(key=lambda c: (severity_order[c.severity], -c.volume_mm3))
    return collisions


def check_clearance(
    parts: dict[str, Shape],
    engine: CadEngine,
    min_gap_mm: float = 0.2,
) -> list[ClearanceViolation]:
    """Verify that all part pairs maintain a minimum air gap.

    Uses AABB-based gap estimation as a fast first pass.  Pairs whose
    bounding boxes are separated by more than *min_gap_mm* are assumed
    to satisfy clearance without further checks.

    Parameters
    ----------
    parts : dict[str, Shape]
        Mapping of part name to engine Shape.
    engine : CadEngine
        The CAD engine to use for bounding-box measurement.
    min_gap_mm : float
        The minimum required clearance between any two parts.

    Returns
    -------
    list[ClearanceViolation]
        One entry per pair that violates clearance, sorted by the size
        of the violation (worst first).
    """
    if len(parts) < 2:
        return []

    bboxes: dict[str, BoundingBox] = {}
    for name, shape in parts.items():
        try:
            bboxes[name] = engine.measure_bounding_box(shape)
        except Exception:
            continue

    violations: list[ClearanceViolation] = []
    for name_a, name_b in combinations(parts, 2):
        bb_a = bboxes.get(name_a)
        bb_b = bboxes.get(name_b)
        if bb_a is None or bb_b is None:
            continue

        gap = _aabb_min_gap(bb_a, bb_b)
        if gap < min_gap_mm:
            violations.append(
                ClearanceViolation(
                    part_a=name_a,
                    part_b=name_b,
                    actual_gap_mm=gap,
                    required_gap_mm=min_gap_mm,
                )
            )

    # Worst violations first (smallest / most negative gap)
    violations.sort(key=lambda v: v.actual_gap_mm)
    return violations
