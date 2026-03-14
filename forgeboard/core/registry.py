"""
Component registry for ForgeBoard.

Loads, stores, and queries ``ComponentSpec`` records.  Registry files use YAML
format inspired by the Clear Skies christmas_tree_registry.yaml schema but
generalized for arbitrary projects.

Thread-safe: all mutating operations acquire a lock so the registry can be
shared across threads (e.g. in an MCP server context).

Example YAML layout::

    version: "1.0"
    project: "Desk Lamp"

    components:
      structure:
        - id: "LAMP-MECH-001"
          name: "Base_Plate"
          ...
      electronics:
        - id: "LAMP-ELEC-001"
          name: "LED_Module"
          ...

The top-level ``components`` key maps category names to lists of component
dicts.  Each dict is validated as a ``ComponentSpec``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

import yaml

from forgeboard.core.types import (
    ComponentSpec,
    InterfacePoint,
    InterfaceType,
    Material,
    Severity,
    ValidationResult,
    Vector3,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML parsing helpers
# ---------------------------------------------------------------------------


def _parse_vector3(data: Any) -> Vector3:
    """Coerce a dict, list, or scalar into a ``Vector3``."""
    if isinstance(data, Vector3):
        return data
    if isinstance(data, dict):
        return Vector3(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            z=float(data.get("z", 0.0)),
        )
    if isinstance(data, (list, tuple)) and len(data) >= 3:
        return Vector3(x=float(data[0]), y=float(data[1]), z=float(data[2]))
    return Vector3()


def _parse_interface(name: str, raw: dict[str, Any]) -> InterfacePoint:
    """Build an ``InterfacePoint`` from a YAML dict."""
    itype_str = raw.get("type", "planar")
    try:
        itype = InterfaceType(itype_str)
    except ValueError:
        itype = InterfaceType.PLANAR

    return InterfacePoint(
        name=name,
        position=_parse_vector3(raw.get("position", {})),
        normal=_parse_vector3(raw.get("normal", {"x": 0, "y": 0, "z": 1})),
        type=itype,
        diameter_mm=raw.get("diameter_mm"),
        metadata={
            k: v
            for k, v in raw.items()
            if k not in ("position", "normal", "type", "diameter_mm")
        },
    )


def _parse_material(raw: dict[str, Any]) -> Material:
    """Build a ``Material`` from a YAML dict."""
    return Material(
        name=raw.get("name", "Unknown"),
        density_g_cm3=float(raw.get("density_g_cm3", 1.0)),
        yield_strength_mpa=raw.get("yield_strength_mpa"),
        thermal_conductivity=raw.get("thermal_conductivity"),
        cost_per_kg=raw.get("cost_per_kg"),
        manufacturing_methods=raw.get("manufacturing_methods", []),
    )


def _parse_component(raw: dict[str, Any], category: str) -> ComponentSpec:
    """Build a ``ComponentSpec`` from a single YAML component dict."""
    # Material: accept either a nested dict or a plain string name
    material_raw = raw.get("material")
    material: Optional[Material] = None
    if isinstance(material_raw, dict):
        material = _parse_material(material_raw)
    elif isinstance(material_raw, str) and "density_g_cm3" in raw:
        material = Material(
            name=material_raw,
            density_g_cm3=float(raw["density_g_cm3"]),
            yield_strength_mpa=raw.get("yield_strength_mpa"),
            thermal_conductivity=raw.get("thermal_conductivity"),
            cost_per_kg=raw.get("cost_per_kg"),
            manufacturing_methods=raw.get("manufacturing_methods", []),
        )

    # Interfaces: a dict of name -> properties
    raw_interfaces = raw.get("interfaces", {})
    interfaces: dict[str, InterfacePoint] = {}
    if isinstance(raw_interfaces, dict):
        for iname, idata in raw_interfaces.items():
            if isinstance(idata, dict):
                interfaces[iname] = _parse_interface(iname, idata)

    # Procurement
    procurement: dict[str, Any] = {}
    raw_proc = raw.get("procurement", {})
    if isinstance(raw_proc, dict):
        procurement = raw_proc

    return ComponentSpec(
        name=raw.get("name", "Unnamed"),
        id=raw.get("id", "UNKNOWN"),
        description=raw.get("description", ""),
        category=category,
        material=material,
        dimensions=raw.get("dimensions", {}),
        interfaces=interfaces,
        mass_g=raw.get("mass_g"),
        is_cots=raw.get("is_cots", False),
        procurement=procurement,
        metadata={
            k: v
            for k, v in raw.items()
            if k
            not in (
                "name",
                "id",
                "description",
                "material",
                "density_g_cm3",
                "yield_strength_mpa",
                "thermal_conductivity",
                "cost_per_kg",
                "manufacturing_methods",
                "dimensions",
                "interfaces",
                "mass_g",
                "is_cots",
                "procurement",
            )
        },
    )


# ---------------------------------------------------------------------------
# Spec-level validation
# ---------------------------------------------------------------------------


def _validate_spec(spec: ComponentSpec) -> list[ValidationResult]:
    """Run basic sanity checks on a single ComponentSpec."""
    results: list[ValidationResult] = []

    # Dimensions should be present
    if not spec.dimensions:
        results.append(
            ValidationResult(
                passed=False,
                severity=Severity.WARNING,
                message=f"Component '{spec.id}' has no dimensions defined",
                check_name="spec_dimensions_present",
            )
        )

    # Dimensions should have positive numeric values
    for key, value in spec.dimensions.items():
        if isinstance(value, (int, float)) and value <= 0:
            results.append(
                ValidationResult(
                    passed=False,
                    severity=Severity.WARNING,
                    message=(
                        f"Component '{spec.id}' dimension '{key}' "
                        f"is non-positive ({value})"
                    ),
                    check_name="spec_dimension_positive",
                    details={"dimension": key, "value": value},
                )
            )

    # Mass should be provided
    if spec.mass_g is None:
        results.append(
            ValidationResult(
                passed=False,
                severity=Severity.INFO,
                message=f"Component '{spec.id}' has no mass_g defined",
                check_name="spec_mass_present",
            )
        )

    return results


# ---------------------------------------------------------------------------
# ComponentRegistry
# ---------------------------------------------------------------------------


class ComponentRegistry:
    """Thread-safe, category-aware registry of component specifications.

    Components are indexed by their unique ``id`` field and optionally
    grouped by ``category``.

    Usage::

        reg = ComponentRegistry()
        reg.load(Path("registry.yaml"))
        spec = reg.get("LAMP-MECH-001")
        all_structure = reg.list_by_category("structure")
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._specs: dict[str, ComponentSpec] = {}  # id -> spec
        self._categories: dict[str, list[str]] = {}  # category -> [ids]
        self._load_warnings: list[ValidationResult] = []

    # -- Loading --------------------------------------------------------------

    def load(self, path: str | Path) -> list[ValidationResult]:
        """Load components from a YAML registry file.

        Returns a list of ``ValidationResult`` for any issues found during
        parsing or validation.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Registry file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Registry file must contain a YAML mapping: {path}")

        components_section = data.get("components", {})
        if not isinstance(components_section, dict):
            raise ValueError(
                f"'components' key must map categories to component lists: {path}"
            )

        warnings: list[ValidationResult] = []

        with self._lock:
            for category, component_list in components_section.items():
                if not isinstance(component_list, list):
                    warnings.append(
                        ValidationResult(
                            passed=False,
                            severity=Severity.WARNING,
                            message=(
                                f"Category '{category}' is not a list, skipping"
                            ),
                            check_name="registry_load",
                        )
                    )
                    continue

                for raw in component_list:
                    if not isinstance(raw, dict):
                        continue
                    try:
                        spec = _parse_component(raw, category)
                        spec_warnings = _validate_spec(spec)
                        warnings.extend(spec_warnings)
                        self._specs[spec.id] = spec
                        self._categories.setdefault(category, [])
                        if spec.id not in self._categories[category]:
                            self._categories[category].append(spec.id)
                    except Exception as exc:
                        warnings.append(
                            ValidationResult(
                                passed=False,
                                severity=Severity.ERROR,
                                message=(
                                    f"Failed to parse component in "
                                    f"'{category}': {exc}"
                                ),
                                check_name="registry_parse",
                                details={"raw": raw},
                            )
                        )

            self._load_warnings = warnings

        logger.info(
            "Loaded %d components from %s (%d warnings)",
            len(self._specs),
            path,
            len(warnings),
        )
        return warnings

    # -- Querying -------------------------------------------------------------

    def get(self, component_id: str) -> Optional[ComponentSpec]:
        """Return the spec for *component_id*, or ``None`` if not found."""
        with self._lock:
            return self._specs.get(component_id)

    def list_all(self) -> list[ComponentSpec]:
        """Return all registered specs, sorted by id."""
        with self._lock:
            return sorted(self._specs.values(), key=lambda s: s.id)

    def list_by_category(self, category: str) -> list[ComponentSpec]:
        """Return all specs in the given category, sorted by id."""
        with self._lock:
            ids = self._categories.get(category, [])
            return sorted(
                [self._specs[cid] for cid in ids if cid in self._specs],
                key=lambda s: s.id,
            )

    def categories(self) -> list[str]:
        """Return sorted list of known category names."""
        with self._lock:
            return sorted(self._categories.keys())

    def search(self, query: str) -> list[ComponentSpec]:
        """Case-insensitive substring search across id, name, and description."""
        q = query.lower()
        with self._lock:
            return [
                spec
                for spec in self._specs.values()
                if q in spec.id.lower()
                or q in spec.name.lower()
                or q in spec.description.lower()
            ]

    # -- Mutation -------------------------------------------------------------

    def add(self, spec: ComponentSpec) -> list[ValidationResult]:
        """Add a single spec to the registry.  Returns validation warnings."""
        warnings = _validate_spec(spec)
        with self._lock:
            self._specs[spec.id] = spec
            self._categories.setdefault(spec.category, [])
            if spec.id not in self._categories[spec.category]:
                self._categories[spec.category].append(spec.id)
        return warnings

    def remove(self, component_id: str) -> bool:
        """Remove a component by id.  Returns True if it existed."""
        with self._lock:
            spec = self._specs.pop(component_id, None)
            if spec is None:
                return False
            cat_ids = self._categories.get(spec.category, [])
            if component_id in cat_ids:
                cat_ids.remove(component_id)
            return True

    # -- Serialization --------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Write the registry to a YAML file.

        The output follows the same schema that ``load()`` expects, so
        round-tripping is supported.
        """
        path = Path(path)
        with self._lock:
            components_by_category: dict[str, list[dict[str, Any]]] = {}
            for spec in self._specs.values():
                cat = spec.category
                components_by_category.setdefault(cat, [])
                entry: dict[str, Any] = {
                    "id": spec.id,
                    "name": spec.name,
                }
                if spec.description:
                    entry["description"] = spec.description
                if spec.material is not None:
                    entry["material"] = {
                        "name": spec.material.name,
                        "density_g_cm3": spec.material.density_g_cm3,
                    }
                    if spec.material.yield_strength_mpa is not None:
                        entry["material"]["yield_strength_mpa"] = (
                            spec.material.yield_strength_mpa
                        )
                    if spec.material.thermal_conductivity is not None:
                        entry["material"]["thermal_conductivity"] = (
                            spec.material.thermal_conductivity
                        )
                    if spec.material.cost_per_kg is not None:
                        entry["material"]["cost_per_kg"] = spec.material.cost_per_kg
                    if spec.material.manufacturing_methods:
                        entry["material"]["manufacturing_methods"] = (
                            spec.material.manufacturing_methods
                        )
                if spec.dimensions:
                    entry["dimensions"] = spec.dimensions
                if spec.interfaces:
                    ifaces: dict[str, dict[str, Any]] = {}
                    for iname, ipt in spec.interfaces.items():
                        iface_dict: dict[str, Any] = {
                            "type": ipt.type.value,
                            "position": {
                                "x": ipt.position.x,
                                "y": ipt.position.y,
                                "z": ipt.position.z,
                            },
                            "normal": {
                                "x": ipt.normal.x,
                                "y": ipt.normal.y,
                                "z": ipt.normal.z,
                            },
                        }
                        if ipt.diameter_mm is not None:
                            iface_dict["diameter_mm"] = ipt.diameter_mm
                        if ipt.metadata:
                            iface_dict.update(ipt.metadata)
                        ifaces[iname] = iface_dict
                    entry["interfaces"] = ifaces
                if spec.mass_g is not None:
                    entry["mass_g"] = spec.mass_g
                if spec.is_cots:
                    entry["is_cots"] = True
                if spec.procurement:
                    entry["procurement"] = spec.procurement
                if spec.metadata:
                    entry.update(spec.metadata)

                components_by_category[cat].append(entry)

        output: dict[str, Any] = {
            "version": "1.0",
            "components": components_by_category,
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                output,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

    # -- Introspection --------------------------------------------------------

    @property
    def load_warnings(self) -> list[ValidationResult]:
        """Warnings produced during the last ``load()`` call."""
        with self._lock:
            return list(self._load_warnings)

    def __len__(self) -> int:
        with self._lock:
            return len(self._specs)

    def __contains__(self, component_id: str) -> bool:
        with self._lock:
            return component_id in self._specs

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"ComponentRegistry({len(self._specs)} components, "
                f"{len(self._categories)} categories)"
            )
