"""Abstract CAD engine protocol and supporting types.

Defines the ``CadEngine`` protocol that every backend (build123d, CadQuery,
FreeCAD, ...) must implement, plus the ``Shape`` wrapper, ``CollisionResult``,
and the ``EngineRegistry`` singleton for discovering available engines at
runtime.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from forgeboard.core.types import BoundingBox, Vector3


# ---------------------------------------------------------------------------
# Shape -- thin wrapper around engine-specific geometry
# ---------------------------------------------------------------------------

@dataclass
class Shape:
    """Engine-agnostic wrapper around native geometry.

    Attributes
    ----------
    native : Any
        The engine-specific geometry object (e.g. a build123d ``Part``).
    name : str
        Human-readable label for this shape.
    material : str | None
        Material name (used for rendering / mass calculations).
    mass_kg : float | None
        Override mass.  When *None* the engine may compute it from volume
        and material density.
    metadata : dict
        Arbitrary key-value store for engine-specific or user data.
    """

    native: Any
    name: str = ""
    material: Optional[str] = None
    mass_kg: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# CollisionResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CollisionResult:
    """Result of a pairwise collision check.

    Attributes
    ----------
    has_collision : bool
        True when the two shapes physically overlap beyond the tolerance.
    volume_mm3 : float
        Volume of the intersection region in cubic millimetres.
    intersection_shape : Shape | None
        The geometry of the intersection, when available.
    """

    has_collision: bool
    volume_mm3: float = 0.0
    intersection_shape: Optional[Shape] = None


# ---------------------------------------------------------------------------
# CadEngine protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class CadEngine(Protocol):
    """Protocol that every CAD backend must satisfy.

    All lengths are in millimetres, angles in degrees, unless stated
    otherwise in a specific method's docstring.
    """

    # -- primitive creation -------------------------------------------------

    def create_box(self, length: float, width: float, height: float) -> Shape:
        """Create an axis-aligned box centred at the origin."""
        ...

    def create_cylinder(self, radius: float, height: float) -> Shape:
        """Create a cylinder along the Z axis, base at z=0."""
        ...

    def create_from_script(self, script: str) -> Shape:
        """Execute a backend-specific script and return the resulting shape."""
        ...

    # -- boolean operations -------------------------------------------------

    def boolean_union(self, a: Shape, b: Shape) -> Shape:
        """Return the union (fuse) of *a* and *b*."""
        ...

    def boolean_subtract(self, a: Shape, b: Shape) -> Shape:
        """Return *a* with *b* removed (cut)."""
        ...

    def boolean_intersect(self, a: Shape, b: Shape) -> Shape:
        """Return the intersection of *a* and *b*."""
        ...

    # -- measurement --------------------------------------------------------

    def measure_bounding_box(self, shape: Shape) -> BoundingBox:
        """Return the axis-aligned bounding box."""
        ...

    def measure_volume(self, shape: Shape) -> float:
        """Return volume in mm^3."""
        ...

    def measure_center_of_mass(self, shape: Shape) -> tuple[float, float, float]:
        """Return the centre of mass as (x, y, z) in mm."""
        ...

    # -- collision ----------------------------------------------------------

    def check_collision(self, a: Shape, b: Shape) -> CollisionResult:
        """Check whether *a* and *b* intersect."""
        ...

    # -- transforms ---------------------------------------------------------

    def move(self, shape: Shape, x: float, y: float, z: float) -> Shape:
        """Translate *shape* by the given offset and return the result."""
        ...

    def rotate(
        self, shape: Shape, axis: tuple[float, float, float], angle_deg: float
    ) -> Shape:
        """Rotate *shape* around *axis* through the origin."""
        ...

    # -- export / rendering -------------------------------------------------

    def export_step(self, shape: Shape, path: str) -> None:
        """Write *shape* to a STEP file at *path*."""
        ...

    def export_stl(self, shape: Shape, path: str) -> None:
        """Write *shape* to an STL file at *path*."""
        ...

    def render_svg(self, shape: Shape, view: str, path: str) -> None:
        """Render an SVG projection of *shape*.

        Parameters
        ----------
        view : str
            One of ``"front"``, ``"top"``, ``"right"``, ``"iso"``.
        path : str
            Destination file path.
        """
        ...


# ---------------------------------------------------------------------------
# EngineRegistry -- singleton factory
# ---------------------------------------------------------------------------

class EngineRegistry:
    """Global registry of available CAD engine backends.

    Usage::

        EngineRegistry.register("build123d", Build123dEngine)
        engine = EngineRegistry.get_engine("build123d")

    The registry is thread-safe.
    """

    _lock: threading.Lock = threading.Lock()
    _engines: dict[str, Callable[..., CadEngine]] = {}

    @classmethod
    def register(cls, name: str, factory: Callable[..., CadEngine]) -> None:
        """Register a factory callable under *name*.

        Parameters
        ----------
        name : str
            Short identifier, e.g. ``"build123d"``, ``"cadquery"``.
        factory : callable
            Zero-argument callable that returns a ``CadEngine`` instance.
        """
        with cls._lock:
            cls._engines[name] = factory

    @classmethod
    def get_engine(cls, name: str) -> CadEngine:
        """Instantiate and return the engine registered under *name*.

        Raises
        ------
        KeyError
            If *name* has not been registered.
        """
        with cls._lock:
            if name not in cls._engines:
                available = ", ".join(sorted(cls._engines)) or "(none)"
                raise KeyError(
                    f"No CAD engine registered as {name!r}. "
                    f"Available engines: {available}"
                )
            factory = cls._engines[name]
        return factory()

    @classmethod
    def available(cls) -> list[str]:
        """Return sorted list of registered engine names."""
        with cls._lock:
            return sorted(cls._engines)

    @classmethod
    def clear(cls) -> None:
        """Remove all registered engines (mainly for tests)."""
        with cls._lock:
            cls._engines.clear()
