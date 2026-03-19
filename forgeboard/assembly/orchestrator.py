"""Assembly orchestrator: builds, solves, validates, and exports assemblies.

Defines the ``Assembly`` (mutable builder) and ``SolvedAssembly`` (frozen
result) data structures, plus the orchestration logic that takes a set of
parts with constraints and produces a fully positioned assembly with
collision and validation reports.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("forgeboard.assembly")

from forgeboard.assembly.collision import (
    Collision,
    ClearanceViolation,
    check_clearance,
    check_pairwise_collisions,
)
from forgeboard.assembly.constraints import Constraint
from forgeboard.core.types import (
    BoundingBox,
    InterfacePoint,
    Placement,
    ValidationResult,
    ValidationSeverity,
    Vector3,
)
from forgeboard.engines.base import CadEngine, Shape


# ---------------------------------------------------------------------------
# Part entry -- internal bookkeeping for an unsolved part
# ---------------------------------------------------------------------------

@dataclass
class _PartEntry:
    """Internal record for a part added to an Assembly before solving."""

    name: str
    shape: Shape
    interfaces: dict[str, InterfacePoint] = field(default_factory=dict)
    at_origin: bool = False
    constraints: list[Constraint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation pipeline
# ---------------------------------------------------------------------------

# A validation rule is a callable that takes the solved state and returns
# zero or more ValidationResult items.
ValidationRule = Callable[["SolvedAssembly", CadEngine], list[ValidationResult]]


@dataclass
class ValidationPipeline:
    """Ordered collection of validation rules to run against a solved assembly.

    Rules are callables with signature::

        (solved: SolvedAssembly, engine: CadEngine) -> list[ValidationResult]
    """

    rules: list[ValidationRule] = field(default_factory=list)

    def add_rule(self, rule: ValidationRule) -> None:
        self.rules.append(rule)

    def run(
        self, solved: SolvedAssembly, engine: CadEngine
    ) -> ValidationReport:
        results: list[ValidationResult] = []
        for rule in self.rules:
            results.extend(rule(solved, engine))
        passed = all(r.passed for r in results)
        errors = [
            r
            for r in results
            if not r.passed
            and r.severity in (ValidationSeverity.ERROR, ValidationSeverity.CRITICAL)
        ]
        warnings = [
            r
            for r in results
            if not r.passed and r.severity == ValidationSeverity.WARNING
        ]
        return ValidationReport(
            passed=passed,
            results=results,
            error_count=len(errors),
            warning_count=len(warnings),
        )


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationReport:
    """Aggregate result of running a :class:`ValidationPipeline`."""

    passed: bool
    results: tuple[ValidationResult, ...] | list[ValidationResult] = field(
        default_factory=list
    )
    error_count: int = 0
    warning_count: int = 0


# ---------------------------------------------------------------------------
# Solved assembly (frozen output)
# ---------------------------------------------------------------------------

@dataclass
class SolvedAssembly:
    """A fully solved assembly with all part placements resolved.

    Attributes
    ----------
    name : str
        Assembly name.
    parts : dict[str, SolvedPart]
        Mapping of part name to its solved placement and shape.
    collisions : list[Collision]
        Collision report generated during solve.
    clearance_violations : list[ClearanceViolation]
        Clearance violations detected during solve.
    validation_report : ValidationReport | None
        Populated after :meth:`Assembly.validate` is called.
    metadata : dict
        Arbitrary key-value metadata.
    """

    name: str = "Untitled"
    parts: dict[str, SolvedPart] = field(default_factory=dict)
    collisions: list[Collision] = field(default_factory=list)
    clearance_violations: list[ClearanceViolation] = field(default_factory=list)
    validation_report: Optional[ValidationReport] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def part_count(self) -> int:
        return len(self.parts)

    @property
    def has_collisions(self) -> bool:
        return len(self.collisions) > 0

    @property
    def is_valid(self) -> bool:
        if self.validation_report is None:
            return not self.has_collisions
        return self.validation_report.passed and not self.has_collisions


# ---------------------------------------------------------------------------
# Solved part
# ---------------------------------------------------------------------------

@dataclass
class SolvedPart:
    """A part with its resolved placement and shape reference.

    Attributes
    ----------
    name : str
        Part name within the assembly.
    shape : Shape
        The engine shape (possibly transformed to world position).
    placement : Placement
        The solved world-space placement.
    interfaces : dict[str, InterfacePoint]
        Interface points defined on this part.
    """

    name: str
    shape: Shape
    placement: Placement
    interfaces: dict[str, InterfacePoint] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Assembly builder
# ---------------------------------------------------------------------------

class Assembly:
    """Mutable assembly builder.

    Add parts and constraints, then call :meth:`solve` to compute placements.

    Example::

        asm = Assembly("MyAssembly")
        asm.add_part("base", base_shape, at_origin=True, interfaces={...})
        asm.add_part("lid", lid_shape, constraints=[Mate("top", "bottom")])
        solved = asm.solve(engine)
        solved.export(engine, "output.step")
    """

    def __init__(self, name: str = "Untitled") -> None:
        self.name = name
        self._parts: dict[str, _PartEntry] = {}
        self._order: list[str] = []  # insertion order
        self._global_constraints: list[tuple[str, str, Constraint]] = []

    # -- part management ----------------------------------------------------

    def add_part(
        self,
        name: str,
        shape: Shape,
        *,
        at_origin: bool = False,
        constraints: Optional[list[Constraint]] = None,
        interfaces: Optional[dict[str, InterfacePoint]] = None,
    ) -> None:
        """Add a part to the assembly.

        Parameters
        ----------
        name : str
            Unique name for this part within the assembly.
        shape : Shape
            The engine Shape representing the part geometry.
        at_origin : bool
            If True, this part is fixed at the origin and serves as the
            assembly datum.  Exactly one part should have this set.
        constraints : list[Constraint] | None
            Constraints that position this part relative to previously
            added parts.  Each constraint references interfaces by name.
        interfaces : dict[str, InterfacePoint] | None
            Named mating features on this part.
        """
        if name in self._parts:
            raise ValueError(f"Part {name!r} already exists in assembly {self.name!r}")

        entry = _PartEntry(
            name=name,
            shape=shape,
            interfaces=interfaces or {},
            at_origin=at_origin,
            constraints=constraints or [],
        )
        self._parts[name] = entry
        self._order.append(name)

    def add_constraint(
        self,
        part_a_name: str,
        part_b_name: str,
        constraint: Constraint,
    ) -> None:
        """Add a constraint between two named parts.

        Parameters
        ----------
        part_a_name : str
            The reference part (already positioned or at_origin).
        part_b_name : str
            The part to be positioned by this constraint.
        constraint : Constraint
            The geometric relationship to enforce.
        """
        self._global_constraints.append((part_a_name, part_b_name, constraint))

    # -- solving ------------------------------------------------------------

    def solve(
        self,
        engine: CadEngine,
        collision_tolerance_mm3: float = 1.0,
        clearance_min_mm: float = 0.2,
        skip_collisions: bool = False,
    ) -> SolvedAssembly:
        """Iteratively solve all constraints and produce a SolvedAssembly.

        The solver processes parts in insertion order.  Parts marked
        ``at_origin`` get an identity placement.  All other parts are
        positioned by solving their constraints against already-placed parts.

        Parameters
        ----------
        engine : CadEngine
            Engine used for transforms, measurements, and collision checks.
        collision_tolerance_mm3 : float
            Minimum intersection volume to report as a collision.
        clearance_min_mm : float
            Minimum air gap required between parts.

        Returns
        -------
        SolvedAssembly
            Frozen result with placements, collision report, etc.
        """
        _t0 = _time.perf_counter()
        solved_parts: dict[str, SolvedPart] = {}

        # Dry-fit: auto-generate bounding-box geometry for parts that have
        # dimensions metadata but no real CAD shape (native=None).
        proxy_count = 0
        for name in self._order:
            entry = self._parts[name]
            if entry.shape.native is None and "_dimensions" in entry.shape.metadata:
                dims = entry.shape.metadata["_dimensions"]
                length = float(dims.get("length", 0))
                width = float(dims.get("width", 0))
                height = float(dims.get("height", 0))
                if length > 0 and width > 0 and height > 0:
                    proxy = engine.create_box(length, width, height)
                    proxy.name = entry.shape.name
                    proxy.mass_kg = entry.shape.mass_kg
                    proxy.material = entry.shape.material
                    proxy.metadata = entry.shape.metadata
                    proxy.metadata["_is_proxy"] = True
                    entry.shape = proxy
                    proxy_count += 1
        logger.info("  [solve] Created %d bounding-box proxies in %.2fs",
                     proxy_count, _time.perf_counter() - _t0)

        # Build a lookup for constraints declared globally
        global_by_target: dict[str, list[tuple[str, Constraint]]] = {}
        for part_a_name, part_b_name, constraint in self._global_constraints:
            global_by_target.setdefault(part_b_name, []).append(
                (part_a_name, constraint)
            )

        for name in self._order:
            entry = self._parts[name]

            if entry.at_origin:
                placement = Placement.identity()
                solved_parts[name] = SolvedPart(
                    name=name,
                    shape=entry.shape,
                    placement=placement,
                    interfaces=dict(entry.interfaces),
                )
                continue

            # Collect all constraints for this part: inline + global
            all_constraints: list[tuple[str, Constraint]] = []

            # Inline constraints: find the reference part by scanning
            # already-solved parts for matching interfaces.
            for c in entry.constraints:
                ref_name = self._find_reference_part(
                    c.interface_a, solved_parts, entry.name
                )
                if ref_name is not None:
                    all_constraints.append((ref_name, c))

            # Global constraints targeting this part
            if name in global_by_target:
                all_constraints.extend(global_by_target[name])

            if not all_constraints:
                # No constraints -- place at origin with a warning
                placement = Placement.identity()
            else:
                # Use the first constraint to determine placement.
                # (A more advanced solver would combine multiple constraints;
                # for now, first-wins is predictable and debuggable.)
                ref_name, constraint = all_constraints[0]
                ref_part = solved_parts[ref_name]
                ref_iface = ref_part.interfaces.get(constraint.interface_a)
                my_iface = entry.interfaces.get(constraint.interface_b)

                if ref_iface is None or my_iface is None:
                    # Missing interface -- fall back to origin
                    placement = Placement.identity()
                else:
                    placement = constraint.solve(
                        ref_part.placement, ref_iface, my_iface
                    )

            # Apply placement transform to the shape
            transformed = engine.move(
                entry.shape,
                placement.position.x,
                placement.position.y,
                placement.position.z,
            )
            if placement.rotation_angle_deg != 0.0:
                transformed = engine.rotate(
                    transformed,
                    placement.rotation_axis.as_tuple(),
                    placement.rotation_angle_deg,
                )

            solved_parts[name] = SolvedPart(
                name=name,
                shape=transformed,
                placement=placement,
                interfaces=dict(entry.interfaces),
            )

        logger.info("  [solve] Constraint resolution done in %.2fs — %d parts placed",
                     _time.perf_counter() - _t0, len(solved_parts))

        # Collision detection (skip for fast dry-fit layout validation)
        collisions = []
        clearance_violations = []
        if skip_collisions:
            logger.info("  [solve] Skipping collision detection (skip_collisions=True)")
        if not skip_collisions:
            shape_map = {name: sp.shape for name, sp in solved_parts.items()}
            collisions = check_pairwise_collisions(
                shape_map, engine, tolerance_mm3=collision_tolerance_mm3
            )
            clearance_violations = check_clearance(
                shape_map, engine, min_gap_mm=clearance_min_mm
            )

        return SolvedAssembly(
            name=self.name,
            parts=solved_parts,
            collisions=collisions,
            clearance_violations=clearance_violations,
            metadata={"solver": "sequential-first-wins"},
        )

    # -- validation ---------------------------------------------------------

    @staticmethod
    def validate(
        solved: SolvedAssembly,
        pipeline: ValidationPipeline,
        engine: CadEngine,
    ) -> ValidationReport:
        """Run a validation pipeline against a solved assembly.

        Parameters
        ----------
        solved : SolvedAssembly
            The assembly to validate.
        pipeline : ValidationPipeline
            Collection of validation rules to apply.
        engine : CadEngine
            Engine for geometric queries.

        Returns
        -------
        ValidationReport
            Aggregate validation result.
        """
        report = pipeline.run(solved, engine)
        solved.validation_report = report
        return report

    # -- export -------------------------------------------------------------

    @staticmethod
    def export(
        solved: SolvedAssembly,
        engine: CadEngine,
        path: str,
        fmt: str = "step",
    ) -> None:
        """Export a solved assembly to a file.

        Parameters
        ----------
        solved : SolvedAssembly
            The assembly to export.
        engine : CadEngine
            Engine for export operations.
        path : str
            Destination file path.
        fmt : str
            Format string: ``"step"``, ``"stl"``, or ``"svg"``.
        """
        if not solved.parts:
            raise ValueError("Cannot export an empty assembly.")

        # Fuse all shapes into one compound for export
        shapes = list(solved.parts.values())
        compound = shapes[0].shape
        for sp in shapes[1:]:
            compound = engine.boolean_union(compound, sp.shape)

        fmt_lower = fmt.lower()
        if fmt_lower == "step":
            engine.export_step(compound, path)
        elif fmt_lower == "stl":
            engine.export_stl(compound, path)
        elif fmt_lower == "svg":
            engine.render_svg(compound, "iso", path)
        else:
            raise ValueError(
                f"Unsupported export format {fmt!r}. Choose from: step, stl, svg"
            )

    # -- aggregate queries --------------------------------------------------

    @staticmethod
    def get_bounding_box(
        solved: SolvedAssembly, engine: CadEngine
    ) -> BoundingBox:
        """Compute the overall bounding box of the solved assembly.

        Merges the bounding boxes of all placed parts.
        """
        if not solved.parts:
            return BoundingBox(
                x_min=0, y_min=0, z_min=0,
                x_max=0, y_max=0, z_max=0,
            )

        x_mins, y_mins, z_mins = [], [], []
        x_maxs, y_maxs, z_maxs = [], [], []

        for sp in solved.parts.values():
            bb = engine.measure_bounding_box(sp.shape)
            x_mins.append(bb.x_min)
            y_mins.append(bb.y_min)
            z_mins.append(bb.z_min)
            x_maxs.append(bb.x_max)
            y_maxs.append(bb.y_max)
            z_maxs.append(bb.z_max)

        return BoundingBox(
            x_min=min(x_mins),
            y_min=min(y_mins),
            z_min=min(z_mins),
            x_max=max(x_maxs),
            y_max=max(y_maxs),
            z_max=max(z_maxs),
        )

    @staticmethod
    def get_center_of_gravity(
        solved: SolvedAssembly, engine: CadEngine
    ) -> Vector3:
        """Compute the assembly centre of gravity.

        Weights each part by its mass (or volume as a fallback proxy).
        """
        total_mass = 0.0
        weighted = Vector3(x=0.0, y=0.0, z=0.0)

        for sp in solved.parts.values():
            mass = sp.shape.mass_kg
            if mass is None or mass <= 0.0:
                # Fall back to volume in mm^3 as a unit-density proxy
                mass = engine.measure_volume(sp.shape)
            cx, cy, cz = engine.measure_center_of_mass(sp.shape)
            weighted = weighted + Vector3(x=cx, y=cy, z=cz) * mass
            total_mass += mass

        if total_mass <= 0.0:
            return Vector3(x=0.0, y=0.0, z=0.0)
        return weighted * (1.0 / total_mass)

    @staticmethod
    def get_total_mass(solved: SolvedAssembly, engine: CadEngine) -> float:
        """Sum the masses of all parts in the assembly.

        Parts without an explicit ``mass_kg`` are assigned a mass equal to
        their volume in mm^3 (i.e. unit density, as a placeholder).
        """
        total = 0.0
        for sp in solved.parts.values():
            mass = sp.shape.mass_kg
            if mass is None or mass <= 0.0:
                mass = engine.measure_volume(sp.shape)
            total += mass
        return total

    # -- private helpers ----------------------------------------------------

    def _find_reference_part(
        self,
        interface_name: str,
        solved_parts: dict[str, SolvedPart],
        exclude: str,
    ) -> Optional[str]:
        """Find the already-solved part that owns *interface_name*.

        Searches in reverse insertion order (most recently added first) to
        prefer the closest neighbour.
        """
        for name in reversed(self._order):
            if name == exclude:
                continue
            if name not in solved_parts:
                continue
            if interface_name in solved_parts[name].interfaces:
                return name
        return None
