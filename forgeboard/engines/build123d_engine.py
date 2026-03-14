"""build123d implementation of the ``CadEngine`` protocol.

All build123d imports are lazy: the module can be imported and inspected
even when build123d is not installed.  Actual engine instantiation will
raise a clear ``ImportError`` at construction time if the dependency is
missing.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from forgeboard.core.types import BoundingBox
from forgeboard.engines.base import CadEngine, CollisionResult, EngineRegistry, Shape

# ---------------------------------------------------------------------------
# Lazy import helper
# ---------------------------------------------------------------------------

_b3d: Any = None  # populated on first use


def _ensure_build123d() -> Any:
    """Import build123d on first call; cache the module reference."""
    global _b3d
    if _b3d is not None:
        return _b3d
    try:
        import build123d as b3d  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "build123d is required by Build123dEngine but is not installed. "
            "Install it with:  pip install build123d"
        ) from exc
    _b3d = b3d
    return _b3d


# ---------------------------------------------------------------------------
# View direction vectors for SVG rendering
# ---------------------------------------------------------------------------

_VIEW_DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "front": (0, -1, 0),
    "back": (0, 1, 0),
    "top": (0, 0, 1),
    "bottom": (0, 0, -1),
    "right": (1, 0, 0),
    "left": (-1, 0, 0),
    "iso": (-1, -1, 1),
}


# ---------------------------------------------------------------------------
# Collision detection tolerance
# ---------------------------------------------------------------------------

_COLLISION_VOLUME_THRESHOLD_MM3: float = 0.01


# ---------------------------------------------------------------------------
# Engine implementation
# ---------------------------------------------------------------------------

class Build123dEngine:
    """CAD engine backed by the build123d library.

    Satisfies the :class:`~forgeboard.engines.base.CadEngine` protocol.
    """

    def __init__(self) -> None:
        # Force an import check at construction time so callers get a clear
        # error immediately rather than on the first operation.
        _ensure_build123d()

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _wrap(native: Any, name: str = "") -> Shape:
        return Shape(native=native, name=name)

    @staticmethod
    def _unwrap(shape: Shape) -> Any:
        return shape.native

    # -- primitive creation -------------------------------------------------

    def create_box(self, length: float, width: float, height: float) -> Shape:
        b3d = _ensure_build123d()
        with b3d.BuildPart() as builder:
            b3d.Box(length, width, height)
        solid = builder.part
        return self._wrap(solid, name="Box")

    def create_cylinder(self, radius: float, height: float) -> Shape:
        b3d = _ensure_build123d()
        with b3d.BuildPart() as builder:
            b3d.Cylinder(radius, height)
        solid = builder.part
        return self._wrap(solid, name="Cylinder")

    def create_from_script(self, script: str) -> Shape:
        """Execute *script* in a namespace that has build123d imported.

        The script must assign its result to a variable called ``result``.
        """
        b3d = _ensure_build123d()
        namespace: dict[str, Any] = {"build123d": b3d, "b3d": b3d}
        exec(script, namespace)  # noqa: S102 -- intentional dynamic execution
        result = namespace.get("result")
        if result is None:
            raise ValueError(
                "Script must assign the final geometry to a variable named 'result'."
            )
        return self._wrap(result, name="Scripted")

    # -- boolean operations -------------------------------------------------

    def boolean_union(self, a: Shape, b: Shape) -> Shape:
        _ensure_build123d()
        fused = self._unwrap(a).fuse(self._unwrap(b))
        return self._wrap(fused, name=f"{a.name}+{b.name}")

    def boolean_subtract(self, a: Shape, b: Shape) -> Shape:
        _ensure_build123d()
        cut = self._unwrap(a).cut(self._unwrap(b))
        return self._wrap(cut, name=f"{a.name}-{b.name}")

    def boolean_intersect(self, a: Shape, b: Shape) -> Shape:
        _ensure_build123d()
        common = self._unwrap(a).intersect(self._unwrap(b))
        return self._wrap(common, name=f"{a.name}&{b.name}")

    # -- measurement --------------------------------------------------------

    def measure_bounding_box(self, shape: Shape) -> BoundingBox:
        bb = self._unwrap(shape).bounding_box()
        return BoundingBox(
            x_min=bb.min.X,
            y_min=bb.min.Y,
            z_min=bb.min.Z,
            x_max=bb.max.X,
            y_max=bb.max.Y,
            z_max=bb.max.Z,
        )

    def measure_volume(self, shape: Shape) -> float:
        return float(self._unwrap(shape).volume)

    def measure_center_of_mass(self, shape: Shape) -> tuple[float, float, float]:
        com = self._unwrap(shape).center()
        return (float(com.X), float(com.Y), float(com.Z))

    # -- collision detection ------------------------------------------------

    def check_collision(self, a: Shape, b: Shape) -> CollisionResult:
        """Detect collision via boolean intersection.

        If the intersection volume exceeds the internal threshold, a
        collision is reported.
        """
        try:
            intersection = self.boolean_intersect(a, b)
            vol = self.measure_volume(intersection)
        except Exception:
            # If the boolean operation fails (degenerate geometry, etc.)
            # assume no collision rather than crashing the pipeline.
            return CollisionResult(has_collision=False, volume_mm3=0.0)

        has_collision = vol > _COLLISION_VOLUME_THRESHOLD_MM3
        return CollisionResult(
            has_collision=has_collision,
            volume_mm3=vol,
            intersection_shape=intersection if has_collision else None,
        )

    # -- transforms ---------------------------------------------------------

    def move(self, shape: Shape, x: float, y: float, z: float) -> Shape:
        b3d = _ensure_build123d()
        loc = b3d.Location((x, y, z))
        moved = self._unwrap(shape).moved(loc)
        return Shape(
            native=moved,
            name=shape.name,
            material=shape.material,
            mass_kg=shape.mass_kg,
            metadata=dict(shape.metadata),
        )

    def rotate(
        self, shape: Shape, axis: tuple[float, float, float], angle_deg: float
    ) -> Shape:
        b3d = _ensure_build123d()
        ax = b3d.Axis.Z  # default

        # Map common axis tuples to build123d Axis constants for clarity,
        # fall back to a custom Axis for arbitrary directions.
        if axis == (1, 0, 0):
            ax = b3d.Axis.X
        elif axis == (0, 1, 0):
            ax = b3d.Axis.Y
        elif axis == (0, 0, 1):
            ax = b3d.Axis.Z
        else:
            ax = b3d.Axis((0, 0, 0), axis)

        rotated = self._unwrap(shape).rotate(ax, angle_deg)
        return Shape(
            native=rotated,
            name=shape.name,
            material=shape.material,
            mass_kg=shape.mass_kg,
            metadata=dict(shape.metadata),
        )

    # -- export / rendering -------------------------------------------------

    def export_step(self, shape: Shape, path: str) -> None:
        b3d = _ensure_build123d()
        b3d.export_step(self._unwrap(shape), path)

    def export_stl(self, shape: Shape, path: str) -> None:
        b3d = _ensure_build123d()
        b3d.export_stl(self._unwrap(shape), path)

    def render_svg(self, shape: Shape, view: str, path: str) -> None:
        b3d = _ensure_build123d()

        direction = _VIEW_DIRECTIONS.get(view.lower())
        if direction is None:
            valid = ", ".join(sorted(_VIEW_DIRECTIONS))
            raise ValueError(
                f"Unknown view {view!r}. Choose from: {valid}"
            )

        # Normalise direction vector for ExportSVG
        mag = math.sqrt(sum(c * c for c in direction))
        normalised = tuple(c / mag for c in direction)

        visible, hidden = self._unwrap(shape).project_to_viewport(normalised)

        exporter = b3d.ExportSVG(unit=b3d.Unit.MM)
        exporter.add_layer("visible", line_weight=0.5)
        exporter.add_layer("hidden", line_weight=0.25, line_type=b3d.LineType.ISO_DASH)
        exporter.add_shape(visible, layer="visible")
        exporter.add_shape(hidden, layer="hidden")
        exporter.write(path)


# ---------------------------------------------------------------------------
# Auto-register when module is imported
# ---------------------------------------------------------------------------

EngineRegistry.register("build123d", Build123dEngine)
