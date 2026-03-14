"""ForgeBoard core module -- types, registry, validation, dependency tracking,
cascade engine, event bus, and project orchestration."""

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
from forgeboard.core.cascade import (
    AffectedComponent,
    CascadeEngine,
    CascadeListener,
    CascadePreview,
    CascadeResult,
    UpdateStatus,
)
from forgeboard.core.events import (
    ALL_EVENT_TYPES,
    ASSEMBLY_UPDATED,
    BOM_UPDATED,
    COLLISION_DETECTED,
    COMPONENT_CREATED,
    COMPONENT_DELETED,
    COMPONENT_UPDATED,
    COST_CHANGED,
    MASS_CHANGED,
    VALIDATION_FAILED,
    EventBus,
)
from forgeboard.core.project import ForgeProject, MassProperties

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
    # Dependency graph
    "DependencyGraph",
    # Cascade engine
    "CascadeEngine",
    "CascadeResult",
    "CascadePreview",
    "CascadeListener",
    "AffectedComponent",
    "UpdateStatus",
    # Event bus
    "EventBus",
    "COMPONENT_CREATED",
    "COMPONENT_UPDATED",
    "COMPONENT_DELETED",
    "ASSEMBLY_UPDATED",
    "BOM_UPDATED",
    "VALIDATION_FAILED",
    "COLLISION_DETECTED",
    "COST_CHANGED",
    "MASS_CHANGED",
    "ALL_EVENT_TYPES",
    # Project
    "ForgeProject",
    "MassProperties",
]
