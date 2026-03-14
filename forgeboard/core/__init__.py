"""ForgeBoard core module -- types, registry, validation, and dependency tracking."""

from forgeboard.core.types import (
    AXIS_X,
    AXIS_Y,
    AXIS_Z,
    ORIGIN,
    AssemblySpec,
    BOMEntry,
    BoundingBox,
    ComponentRef,
    ComponentSpec,
    ConstraintSpec,
    ConstraintType,
    InterfacePoint,
    InterfaceType,
    Material,
    Placement,
    Severity,
    ValidationResult,
    ValidationSeverity,
    Vector3,
)
from forgeboard.core.registry import ComponentRegistry
from forgeboard.core.validation import (
    DimensionCheck,
    InterfaceCheck,
    MassCheck,
    ValidationCheck,
    ValidationPipeline,
    ValidationReport,
)
from forgeboard.core.dependency_graph import DependencyGraph

__all__ = [
    # Geometry
    "Vector3",
    "BoundingBox",
    "ORIGIN",
    "AXIS_X",
    "AXIS_Y",
    "AXIS_Z",
    # Interfaces
    "InterfacePoint",
    "InterfaceType",
    # Material
    "Material",
    # Component
    "ComponentSpec",
    # Assembly
    "AssemblySpec",
    "ComponentRef",
    "ConstraintSpec",
    "ConstraintType",
    # Validation
    "Severity",
    "ValidationSeverity",
    "ValidationResult",
    "ValidationCheck",
    "ValidationPipeline",
    "ValidationReport",
    "DimensionCheck",
    "MassCheck",
    "InterfaceCheck",
    # BOM
    "BOMEntry",
    # Placement
    "Placement",
    # Registry
    "ComponentRegistry",
    # Dependency
    "DependencyGraph",
]
