"""Top-level project orchestrator for ForgeBoard.

Ties together the component registry, dependency graph, cascade engine,
event bus, assemblies, and BOM generation into a single coherent project.

This is the main entry point for users of ForgeBoard.  It provides a
high-level API for managing a hardware project with reactive updates:
change a dimension on one component and watch the cascade propagate through
the entire dependency graph, updating specs, BOM, and mass properties.

Example::

    project = ForgeProject("Desk Lamp")
    project.add_component(pole_spec)
    project.add_component(bracket_spec)

    # Wire up a dependency
    project.graph.add_dependency(
        "pole.dimensions.outer_diameter",
        "bracket.dimensions.inner_diameter",
        "source + 0.2",
    )

    # Change the pole diameter -- bracket auto-updates
    result = project.update_component("pole", {"dimensions.outer_diameter": 35.0})
    print(f"Affected: {result.total_affected} parameters")
    print(project.summary)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from forgeboard.core.cascade import (
    CascadeEngine,
    CascadePreview,
    CascadeResult,
)
from forgeboard.core.dependency_graph import DependencyGraph
from forgeboard.core.events import (
    BOM_UPDATED,
    COMPONENT_CREATED,
    COMPONENT_DELETED,
    COMPONENT_UPDATED,
    COST_CHANGED,
    MASS_CHANGED,
    EventBus,
)
from forgeboard.core.registry import ComponentRegistry
from forgeboard.core.types import BOMEntry, ComponentSpec, Vector3

if TYPE_CHECKING:
    from forgeboard.assembly.orchestrator import Assembly
    from forgeboard.bom.generator import BillOfMaterials
    from forgeboard.engines.base import CadEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mass properties
# ---------------------------------------------------------------------------


@dataclass
class MassProperties:
    """Aggregated mass properties for a project.

    Attributes:
        total_mass_g: Total mass of all components in grams.
        center_of_gravity: Weighted center of gravity (only meaningful
            when components have known positions in an assembly).
        per_component: Mapping of component_id -> mass in grams.
    """

    total_mass_g: float = 0.0
    center_of_gravity: Vector3 = field(default_factory=Vector3)
    per_component: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ForgeProject
# ---------------------------------------------------------------------------


class ForgeProject:
    """Top-level project container that connects registry, assembly, BOM, and cascade.

    This is the main entry point for ForgeBoard.  It manages a complete
    hardware project with reactive updates.

    Usage::

        project = ForgeProject("My Project")
        project.add_component(component_spec)
        result = project.update_component("comp-id", {"dimensions.width": 50.0})
        bom = project.get_bom()
        print(project.summary)
    """

    def __init__(
        self,
        name: str,
        registry_path: str | None = None,
    ) -> None:
        self.name = name
        self.registry = ComponentRegistry()
        self.graph = DependencyGraph()
        self.cascade = CascadeEngine(self.registry, self.graph)
        self.event_bus = EventBus()
        self.assemblies: dict[str, Any] = {}
        self._engine: Any = None

        # Wire up cascade engine to event bus
        self.cascade.register_listener(_EventBusBridge(self.event_bus))

        # Load registry from file if provided
        if registry_path is not None:
            self.registry.load(registry_path)

    # -- Component management -----------------------------------------------

    def add_component(self, spec: ComponentSpec) -> None:
        """Add a component to the project.

        Registers the spec in the component registry and publishes a
        ``component.created`` event.
        """
        self.registry.add(spec)
        self.event_bus.publish(
            COMPONENT_CREATED,
            {"component_id": spec.id, "name": spec.name},
        )

    def remove_component(self, component_id: str) -> bool:
        """Remove a component from the project.

        Returns True if the component existed and was removed.
        Publishes a ``component.deleted`` event.
        """
        removed = self.registry.remove(component_id)
        if removed:
            self.event_bus.publish(
                COMPONENT_DELETED,
                {"component_id": component_id},
            )
        return removed

    def get_component(self, component_id: str) -> ComponentSpec | None:
        """Look up a component spec by ID."""
        return self.registry.get(component_id)

    def update_component(
        self, component_id: str, changes: dict[str, Any]
    ) -> CascadeResult:
        """Update a component and trigger cascade propagation.

        This is the main reactive entry point.  Changes are applied to the
        specified component, then the cascade engine propagates effects to
        all downstream components in the dependency graph.

        Args:
            component_id: ID of the component to change.
            changes: Dict of field changes, e.g.
                ``{"dimensions.outer_diameter": 35.0}``.

        Returns:
            CascadeResult describing all affected components.
        """
        result = self.cascade.apply_change(component_id, changes)

        # Publish event bus notifications
        self.event_bus.publish(
            COMPONENT_UPDATED,
            {
                "component_id": component_id,
                "changes": changes,
                "cascade_affected": result.total_affected,
            },
        )

        if result.mass_changed:
            self.event_bus.publish(
                MASS_CHANGED,
                {"source": component_id, "total_affected": result.total_affected},
            )

        if result.cost_changed:
            self.event_bus.publish(
                COST_CHANGED,
                {"source": component_id, "total_affected": result.total_affected},
            )

        return result

    def preview_update(
        self, component_id: str, changes: dict[str, Any]
    ) -> CascadePreview:
        """Preview what a change would affect without applying it."""
        return self.cascade.preview_change(component_id, changes)

    # -- Assembly management ------------------------------------------------

    def add_assembly(self, name: str) -> Any:
        """Create a new assembly in the project.

        Returns the Assembly builder for adding parts and constraints.
        """
        # Lazy import to avoid circular dependency with assembly.orchestrator
        from forgeboard.assembly.orchestrator import Assembly as _Assembly

        if name in self.assemblies:
            raise ValueError(
                f"Assembly {name!r} already exists in project {self.name!r}"
            )
        asm = _Assembly(name)
        self.assemblies[name] = asm
        return asm

    def get_assembly(self, name: str) -> Any:
        """Look up an assembly by name."""
        return self.assemblies.get(name)

    # -- BOM ----------------------------------------------------------------

    def get_bom(self) -> Any:
        """Generate current BOM from all registered components.

        Iterates over all components in the registry and produces a
        BillOfMaterials with aggregated totals.  This method does not
        require a solved assembly -- it generates a flat BOM from the
        registry.
        """
        # Lazy import to avoid circular dependency
        from forgeboard.bom.generator import BillOfMaterials as _BillOfMaterials

        entries = []
        total_mass = 0.0
        total_cost = 0.0
        cots_count = 0
        custom_count = 0
        fastener_count = 0

        for spec in self.registry.list_all():
            material_name = spec.material.name if spec.material else ""
            supplier = ""
            unit_cost: float | None = None

            if spec.procurement:
                supplier = str(spec.procurement.get("supplier", ""))
                raw_cost = spec.procurement.get("unit_cost")
                if raw_cost is not None:
                    unit_cost = float(raw_cost)

            total_cost_entry: float | None = None
            if unit_cost is not None:
                total_cost_entry = round(unit_cost, 2)

            mfg_method = str(spec.metadata.get("manufacturing_method", ""))
            is_fastener = bool(spec.metadata.get("is_fastener", False))

            entry = BOMEntry(
                part_name=spec.name,
                part_id=spec.id,
                quantity=1,
                material=material_name,
                mass_g=spec.mass_g,
                unit_cost=unit_cost,
                total_cost=total_cost_entry,
                supplier=supplier,
                is_cots=spec.is_cots,
                manufacturing_method=mfg_method,
            )
            entries.append(entry)

            entry_mass = entry.mass_g if entry.mass_g is not None else 0.0
            entry_cost = entry.total_cost if entry.total_cost is not None else 0.0
            total_mass += entry_mass
            total_cost += entry_cost

            if is_fastener:
                fastener_count += 1
            elif spec.is_cots:
                cots_count += 1
            else:
                custom_count += 1

        return _BillOfMaterials(
            entries=entries,
            total_mass_g=total_mass,
            total_cost=total_cost,
            cots_count=cots_count,
            custom_count=custom_count,
            fastener_count=fastener_count,
        )

    # -- Mass properties ----------------------------------------------------

    def get_mass_properties(self) -> MassProperties:
        """Calculate total mass and per-component breakdown from all components.

        Center of gravity is only meaningful if components have been placed
        in an assembly.  Without placement data, it defaults to the origin.
        """
        per_component: dict[str, float] = {}
        total_mass = 0.0

        for spec in self.registry.list_all():
            mass = spec.mass_g if spec.mass_g is not None else 0.0
            per_component[spec.id] = mass
            total_mass += mass

        return MassProperties(
            total_mass_g=total_mass,
            center_of_gravity=Vector3(x=0.0, y=0.0, z=0.0),
            per_component=per_component,
        )

    # -- Persistence --------------------------------------------------------

    def save(self, path: str) -> None:
        """Save project state (registry + graph + metadata) to a directory.

        Creates the directory if it does not exist.  Writes:
        - ``registry.yaml`` -- component specifications
        - ``graph.json`` -- dependency graph edges
        - ``project.json`` -- project metadata
        """
        out_dir = Path(path)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Save registry
        self.registry.save(out_dir / "registry.yaml")

        # Save dependency graph
        graph_data = {
            "nodes": sorted(self.graph.nodes),
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "formula": e.formula,
                }
                for e in self.graph.edges
            ],
        }
        with open(out_dir / "graph.json", "w", encoding="utf-8") as f:
            json.dump(graph_data, f, indent=2)

        # Save project metadata
        project_data = {
            "name": self.name,
            "component_count": len(self.registry),
            "assembly_names": sorted(self.assemblies.keys()),
        }
        with open(out_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump(project_data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> ForgeProject:
        """Load a project from a directory previously created by save().

        Reads ``project.json``, ``registry.yaml``, and ``graph.json``.
        """
        in_dir = Path(path)

        # Load project metadata
        project_json = in_dir / "project.json"
        if not project_json.exists():
            raise FileNotFoundError(
                f"No project.json found in {in_dir}"
            )

        with open(project_json, "r", encoding="utf-8") as f:
            project_data = json.load(f)

        name = project_data.get("name", "Unnamed")
        project = cls(name)

        # Load registry
        registry_yaml = in_dir / "registry.yaml"
        if registry_yaml.exists():
            project.registry.load(registry_yaml)

        # Load dependency graph
        graph_json = in_dir / "graph.json"
        if graph_json.exists():
            with open(graph_json, "r", encoding="utf-8") as f:
                graph_data = json.load(f)

            for node in graph_data.get("nodes", []):
                project.graph.add_node(node)

            for edge in graph_data.get("edges", []):
                project.graph.add_dependency(
                    edge["source"],
                    edge["target"],
                    formula=edge.get("formula"),
                )

        return project

    # -- CAD engine ---------------------------------------------------------

    def set_engine(self, engine: Any) -> None:
        """Set the CAD engine for geometry operations."""
        self._engine = engine

    @property
    def engine(self) -> Any:
        """The current CAD engine, if any."""
        return self._engine

    # -- Summary ------------------------------------------------------------

    @property
    def summary(self) -> str:
        """Human-readable project summary: components, mass, cost, status."""
        mass_props = self.get_mass_properties()
        bom = self.get_bom()

        lines = [
            f"Project: {self.name}",
            f"{'=' * 50}",
            f"Components: {len(self.registry)}",
            f"Assemblies: {len(self.assemblies)}",
            f"Dependencies: {len(self.graph.edges)} edges across {len(self.graph)} nodes",
            f"",
            f"Mass: {mass_props.total_mass_g:.1f} g",
            f"Cost: ${bom.total_cost:.2f} {bom.currency}",
            f"  COTS: {bom.cots_count}  Custom: {bom.custom_count}  Fasteners: {bom.fastener_count}",
        ]

        if self.assemblies:
            lines.append("")
            lines.append("Assemblies:")
            for asm_name in sorted(self.assemblies):
                lines.append(f"  - {asm_name}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal bridge: CascadeListener -> EventBus
# ---------------------------------------------------------------------------


class _EventBusBridge:
    """Bridges cascade listener callbacks to event bus publications."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def on_component_updated(
        self, component_id: str, changes: dict[str, Any]
    ) -> None:
        self._bus.publish(
            COMPONENT_UPDATED,
            {"component_id": component_id, "changes": changes, "source": "cascade"},
        )

    def on_cascade_complete(self, result: CascadeResult) -> None:
        if result.bom_changed:
            self._bus.publish(
                BOM_UPDATED,
                {
                    "source_component": result.source_component,
                    "total_affected": result.total_affected,
                },
            )
