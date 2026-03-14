"""
Core data types for ForgeBoard.

Pydantic v2 models representing the fundamental abstractions for CAD assembly
management: geometry primitives, materials, component specifications, assembly
definitions, constraints, validation results, and bill-of-materials entries.

All length values are in millimeters unless explicitly noted otherwise.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------


class Vector3(BaseModel):
    """A point or direction in 3-D space (millimeters).

    Supports arithmetic (``+``, ``-``, ``*``, unary ``-``), dot/cross
    products, and magnitude/normalization helpers.

    Frozen so it can be used as a dict key or in frozen containers.
    """

    model_config = {"frozen": True}

    x: float = Field(default=0.0, description="X coordinate (mm)")
    y: float = Field(default=0.0, description="Y coordinate (mm)")
    z: float = Field(default=0.0, description="Z coordinate (mm)")

    # -- Arithmetic -----------------------------------------------------------

    def __add__(self, other: object) -> Vector3:
        if not isinstance(other, Vector3):
            return NotImplemented
        return Vector3(x=self.x + other.x, y=self.y + other.y, z=self.z + other.z)

    def __sub__(self, other: object) -> Vector3:
        if not isinstance(other, Vector3):
            return NotImplemented
        return Vector3(x=self.x - other.x, y=self.y - other.y, z=self.z - other.z)

    def __mul__(self, scalar: float) -> Vector3:
        return Vector3(x=self.x * scalar, y=self.y * scalar, z=self.z * scalar)

    def __rmul__(self, scalar: float) -> Vector3:
        return self.__mul__(scalar)

    def __neg__(self) -> Vector3:
        return Vector3(x=-self.x, y=-self.y, z=-self.z)

    # -- Linear algebra -------------------------------------------------------

    def dot(self, other: Vector3) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vector3) -> Vector3:
        """Cross product."""
        return Vector3(
            x=self.y * other.z - self.z * other.y,
            y=self.z * other.x - self.x * other.z,
            z=self.x * other.y - self.y * other.x,
        )

    def length(self) -> float:
        """Euclidean magnitude."""
        return math.sqrt(self.dot(self))

    def normalized(self) -> Vector3:
        """Return a unit-length copy, or zero vector if magnitude is negligible."""
        mag = self.length()
        if mag < 1e-12:
            return Vector3(x=0.0, y=0.0, z=0.0)
        return self * (1.0 / mag)

    def as_tuple(self) -> tuple[float, float, float]:
        """Return (x, y, z) as a plain tuple."""
        return (self.x, self.y, self.z)

    def __repr__(self) -> str:
        return f"Vector3({self.x:.3f}, {self.y:.3f}, {self.z:.3f})"


# Convenience constants
ORIGIN = Vector3(x=0.0, y=0.0, z=0.0)
AXIS_X = Vector3(x=1.0, y=0.0, z=0.0)
AXIS_Y = Vector3(x=0.0, y=1.0, z=0.0)
AXIS_Z = Vector3(x=0.0, y=0.0, z=1.0)


class BoundingBox(BaseModel):
    """Axis-aligned bounding box.

    Accepts either ``min_corner`` / ``max_corner`` Vector3s, or the six
    scalar keyword arguments ``x_min`` through ``z_max`` for backward
    compatibility with the previous dataclass-based API.
    """

    min_corner: Vector3 = Field(
        default_factory=Vector3,
        description="Minimum corner (lowest x, y, z)",
    )
    max_corner: Vector3 = Field(
        default_factory=Vector3,
        description="Maximum corner (highest x, y, z)",
    )

    # Alternate scalar-field constructor for backward compat:
    #   BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=10, z_max=10)

    def __init__(
        self,
        *,
        min_corner: Optional[Vector3] = None,
        max_corner: Optional[Vector3] = None,
        x_min: Optional[float] = None,
        y_min: Optional[float] = None,
        z_min: Optional[float] = None,
        x_max: Optional[float] = None,
        y_max: Optional[float] = None,
        z_max: Optional[float] = None,
    ) -> None:
        scalars_given = any(
            v is not None for v in (x_min, y_min, z_min, x_max, y_max, z_max)
        )
        if scalars_given:
            min_corner = Vector3(
                x=x_min if x_min is not None else 0.0,
                y=y_min if y_min is not None else 0.0,
                z=z_min if z_min is not None else 0.0,
            )
            max_corner = Vector3(
                x=x_max if x_max is not None else 0.0,
                y=y_max if y_max is not None else 0.0,
                z=z_max if z_max is not None else 0.0,
            )
        if min_corner is None:
            min_corner = Vector3()
        if max_corner is None:
            max_corner = Vector3()
        super().__init__(min_corner=min_corner, max_corner=max_corner)

    @model_validator(mode="after")
    def _validate_corners(self) -> BoundingBox:
        if self.min_corner.x > self.max_corner.x:
            raise ValueError(
                f"min_corner.x ({self.min_corner.x}) > "
                f"max_corner.x ({self.max_corner.x})"
            )
        if self.min_corner.y > self.max_corner.y:
            raise ValueError(
                f"min_corner.y ({self.min_corner.y}) > "
                f"max_corner.y ({self.max_corner.y})"
            )
        if self.min_corner.z > self.max_corner.z:
            raise ValueError(
                f"min_corner.z ({self.min_corner.z}) > "
                f"max_corner.z ({self.max_corner.z})"
            )
        return self

    # -- Scalar accessors (backward compat) -----------------------------------

    @property
    def x_min(self) -> float:
        return self.min_corner.x

    @property
    def y_min(self) -> float:
        return self.min_corner.y

    @property
    def z_min(self) -> float:
        return self.min_corner.z

    @property
    def x_max(self) -> float:
        return self.max_corner.x

    @property
    def y_max(self) -> float:
        return self.max_corner.y

    @property
    def z_max(self) -> float:
        return self.max_corner.z

    # -- Derived geometry -----------------------------------------------------

    @property
    def size_x(self) -> float:
        return self.max_corner.x - self.min_corner.x

    @property
    def size_y(self) -> float:
        return self.max_corner.y - self.min_corner.y

    @property
    def size_z(self) -> float:
        return self.max_corner.z - self.min_corner.z

    @property
    def center(self) -> Vector3:
        return Vector3(
            x=(self.min_corner.x + self.max_corner.x) / 2,
            y=(self.min_corner.y + self.max_corner.y) / 2,
            z=(self.min_corner.z + self.max_corner.z) / 2,
        )

    @property
    def volume(self) -> float:
        return self.size_x * self.size_y * self.size_z

    def overlaps(self, other: BoundingBox, margin: float = 0.0) -> bool:
        """Return True if this box overlaps *other*, optionally expanded by *margin*."""
        return not (
            self.max_corner.x + margin < other.min_corner.x - margin
            or self.min_corner.x - margin > other.max_corner.x + margin
            or self.max_corner.y + margin < other.min_corner.y - margin
            or self.min_corner.y - margin > other.max_corner.y + margin
            or self.max_corner.z + margin < other.min_corner.z - margin
            or self.min_corner.z - margin > other.max_corner.z + margin
        )

    def expanded(self, margin: float) -> BoundingBox:
        """Return a new bounding box expanded by *margin* on every side."""
        return BoundingBox(
            min_corner=Vector3(
                x=self.min_corner.x - margin,
                y=self.min_corner.y - margin,
                z=self.min_corner.z - margin,
            ),
            max_corner=Vector3(
                x=self.max_corner.x + margin,
                y=self.max_corner.y + margin,
                z=self.max_corner.z + margin,
            ),
        )


# ---------------------------------------------------------------------------
# Interface points
# ---------------------------------------------------------------------------


class InterfaceType(str, Enum):
    """Geometric type of a connection surface."""

    PLANAR = "planar"
    CYLINDRICAL = "cylindrical"
    SPHERICAL = "spherical"


class InterfacePoint(BaseModel):
    """A named connection point on a component.

    Represents where one part physically mates with another: bolt circles,
    bore fits, saddle grooves, pin slots, etc.
    """

    name: str = Field(description="Human-readable interface name (e.g. 'pole_bore')")
    position: Vector3 = Field(
        default_factory=Vector3,
        description="Location in part-local coordinates (mm)",
    )
    normal: Vector3 = Field(
        default_factory=lambda: Vector3(x=0.0, y=0.0, z=1.0),
        description="Outward-facing normal vector at the interface",
    )
    type: InterfaceType = Field(
        default=InterfaceType.PLANAR,
        description="Geometric surface type",
    )
    diameter_mm: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Diameter for cylindrical / spherical interfaces (mm)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form metadata (bolt patterns, notes, etc.)",
    )

    def flipped(self) -> InterfacePoint:
        """Return a copy with the normal reversed."""
        return self.model_copy(update={"normal": -self.normal})


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


class Material(BaseModel):
    """Physical material properties used for mass, cost, and thermal analysis."""

    model_config = {"frozen": True}

    name: str = Field(description="Material name (e.g. 'Aluminum_6061')")
    density_g_cm3: float = Field(
        gt=0.0,
        description="Density in grams per cubic centimeter",
    )
    yield_strength_mpa: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Yield strength in megapascals",
    )
    thermal_conductivity: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Thermal conductivity in W/(m*K)",
    )
    cost_per_kg: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Raw material cost per kilogram (USD)",
    )
    manufacturing_methods: list[str] = Field(
        default_factory=list,
        description=(
            "Applicable methods (e.g. 'CNC milling', '3D print', 'injection molding')"
        ),
    )


# ---------------------------------------------------------------------------
# Component specification
# ---------------------------------------------------------------------------


class ComponentSpec(BaseModel):
    """Full specification of a single part or purchased item.

    This is the canonical record stored in the component registry.  Its
    structure is inspired by the Clear Skies christmas_tree_registry.yaml
    format but generalized for any project.
    """

    name: str = Field(description="Human-readable component name")
    id: str = Field(description="Unique component identifier (e.g. 'LAMP-MECH-001')")
    description: str = Field(
        default="",
        description="Free-text description of the component's role",
    )
    category: str = Field(
        default="uncategorized",
        description="Grouping category (structure, electronics, sensors, ...)",
    )
    material: Optional[Material] = Field(
        default=None,
        description="Primary material specification",
    )
    dimensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Key dimensions as name->value pairs (all in mm unless noted)",
    )
    interfaces: dict[str, InterfacePoint] = Field(
        default_factory=dict,
        description="Named connection / attachment points",
    )
    mass_g: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Component mass in grams",
    )
    is_cots: bool = Field(
        default=False,
        description="True if Commercial Off-The-Shelf (purchased, not manufactured)",
    )
    procurement: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Procurement details: supplier, url, sku, unit_cost, lead_time, etc."
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra metadata",
    )

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Component id must not be empty")
        return stripped

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Component name must not be empty")
        return stripped


# ---------------------------------------------------------------------------
# Assembly specification
# ---------------------------------------------------------------------------


class ComponentRef(BaseModel):
    """A reference to a component used inside an assembly."""

    component_id: str = Field(description="ID of the component in the registry")
    instance_name: str = Field(
        description=(
            "Unique instance name within this assembly (e.g. 'left_leg_1')"
        ),
    )
    quantity: int = Field(default=1, ge=1, description="Number of this instance")


class ConstraintType(str, Enum):
    """Types of geometric constraints between parts."""

    MATE = "mate"
    FLUSH = "flush"
    ALIGN = "align"
    OFFSET = "offset"
    ANGLE = "angle"


class ConstraintSpec(BaseModel):
    """A geometric constraint tying two component interfaces together.

    Mirrors CAD assembly constraint concepts: mate two planar faces,
    align cylindrical bores, apply an offset, fix an angle, etc.
    """

    type: ConstraintType = Field(description="Constraint type")
    part_a: str = Field(description="Instance name of the first part")
    interface_a: str = Field(description="Interface name on part_a")
    part_b: str = Field(description="Instance name of the second part")
    interface_b: str = Field(description="Interface name on part_b")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Constraint parameters (offset_mm, angle_deg, etc.)",
    )


class AssemblySpec(BaseModel):
    """Definition of an assembly: which components, how they connect,
    and metadata for downstream processing."""

    name: str = Field(description="Assembly name")
    description: str = Field(default="", description="Assembly description")
    components: list[ComponentRef] = Field(
        default_factory=list,
        description="Ordered list of component references",
    )
    constraints: list[ConstraintSpec] = Field(
        default_factory=list,
        description="Geometric constraints binding component interfaces",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form assembly metadata",
    )


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """Severity level for validation findings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# Backward-compatible alias for code that used the old name
ValidationSeverity = Severity


class ValidationResult(BaseModel):
    """Outcome of a single validation check."""

    passed: bool = Field(description="Whether the check passed")
    severity: Severity = Field(description="Severity if the check failed")
    message: str = Field(description="Human-readable result description")
    check_name: str = Field(
        default="",
        description="Name of the validation check that produced this result",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured details (values checked, thresholds, etc.)",
    )

    # Backward compat: old dataclass version used ``result.rule``
    @property
    def rule(self) -> str:
        return self.check_name


# ---------------------------------------------------------------------------
# Bill of Materials
# ---------------------------------------------------------------------------


class BOMEntry(BaseModel):
    """A single line item in a Bill of Materials."""

    model_config = {"frozen": True}

    part_name: str = Field(description="Human-readable part name")
    part_id: str = Field(description="Component registry ID")
    quantity: int = Field(default=1, ge=1, description="Quantity required")
    material: str = Field(default="", description="Primary material name")
    mass_g: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Mass of one unit in grams",
    )
    unit_cost: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Cost per unit (USD)",
    )
    total_cost: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total line cost (unit_cost * quantity, USD)",
    )
    supplier: str = Field(default="", description="Supplier / vendor name")
    is_cots: bool = Field(default=False, description="Commercial Off-The-Shelf flag")
    manufacturing_method: str = Field(
        default="",
        description="How this part is produced (CNC, 3D print, purchased, ...)",
    )

    @model_validator(mode="after")
    def _compute_total_cost(self) -> BOMEntry:
        """Auto-compute total_cost when unit_cost is provided but total_cost is not."""
        if self.unit_cost is not None and self.total_cost is None:
            object.__setattr__(
                self, "total_cost", round(self.unit_cost * self.quantity, 2)
            )
        return self


# ---------------------------------------------------------------------------
# Placement (rigid-body transform)
# ---------------------------------------------------------------------------


class Placement(BaseModel):
    """Rigid-body placement: translation + axis-angle rotation."""

    position: Vector3 = Field(default_factory=Vector3)
    rotation_axis: Vector3 = Field(default_factory=lambda: AXIS_Z)
    rotation_angle_deg: float = Field(default=0.0)

    @staticmethod
    def identity() -> Placement:
        return Placement()
