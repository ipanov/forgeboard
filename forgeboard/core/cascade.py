"""Reactive change propagation engine for ForgeBoard.

When a component parameter changes (dimensions, material, cost, mass), the
cascade engine:

1. Finds all affected downstream components via the dependency graph.
2. Topologically sorts them to determine safe evaluation order.
3. Evaluates formulas to compute new values for each affected parameter.
4. Updates component specs in the registry.
5. Notifies listeners of each change.

The engine is pure computation -- no LLM calls, no network I/O.  Given the
same graph and changes it always produces the same results.

Example::

    engine = CascadeEngine(registry, graph)
    result = engine.apply_change("pole.outer_diameter", {"dimensions.outer_diameter": 35.0})
    for ac in result.affected_components:
        print(f"{ac.component_id}.{ac.field}: {ac.old_value} -> {ac.new_value}")
"""

from __future__ import annotations

import copy
import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from forgeboard.core.dependency_graph import DependencyGraph
from forgeboard.core.registry import ComponentRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status enum for affected components
# ---------------------------------------------------------------------------


class UpdateStatus(str, Enum):
    """Outcome of updating a single downstream parameter."""

    UPDATED = "updated"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class AffectedComponent:
    """Record of a single downstream parameter that was (or would be) updated.

    Attributes:
        component_id: The component whose parameter changed.
        field: Dotted field path (e.g. "dimensions.inner_diameter").
        old_value: Value before the cascade.
        new_value: Value after formula evaluation.
        formula: The formula string that produced new_value.
        status: Whether the update succeeded, failed, or was skipped.
    """

    component_id: str
    field: str
    old_value: Any = None
    new_value: Any = None
    formula: str = ""
    status: UpdateStatus = UpdateStatus.UPDATED


@dataclass
class CascadeResult:
    """Summary of a completed cascade propagation.

    Attributes:
        source_component: The component that was directly modified.
        source_changes: The changes applied to the source component.
        affected_components: Ordered list of downstream updates.
        total_affected: Number of downstream parameters touched.
        bom_changed: True if any cost or procurement field changed.
        mass_changed: True if any mass_g value changed.
        cost_changed: True if any unit_cost or procurement cost changed.
    """

    source_component: str
    source_changes: dict[str, Any] = field(default_factory=dict)
    affected_components: list[AffectedComponent] = field(default_factory=list)
    total_affected: int = 0
    bom_changed: bool = False
    mass_changed: bool = False
    cost_changed: bool = False


@dataclass
class CascadePreview:
    """Same as CascadeResult but explicitly marked as a preview (not applied).

    The ``applied`` flag is always False.
    """

    source_component: str
    source_changes: dict[str, Any] = field(default_factory=dict)
    affected_components: list[AffectedComponent] = field(default_factory=list)
    total_affected: int = 0
    bom_changed: bool = False
    mass_changed: bool = False
    cost_changed: bool = False
    applied: bool = False


# ---------------------------------------------------------------------------
# Listener protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CascadeListener(Protocol):
    """Protocol for objects that want to observe cascade events."""

    def on_component_updated(
        self, component_id: str, changes: dict[str, Any]
    ) -> None:
        """Called when a component's spec has been updated."""
        ...

    def on_cascade_complete(self, result: CascadeResult) -> None:
        """Called when the entire cascade propagation is done."""
        ...


# ---------------------------------------------------------------------------
# Formula evaluator (sandboxed)
# ---------------------------------------------------------------------------

# Whitelist of safe builtins for formula evaluation.
_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
}


def _evaluate_formula(formula: str, source_value: Any) -> Any:
    """Evaluate a formula string with ``source`` bound to *source_value*.

    The formula runs in a restricted namespace with only safe math builtins.
    For example: ``"source + 1.0"``, ``"max(source, 10)"``.

    If *formula* is None or empty, the identity transform is used (target
    receives the same value as source).

    Raises ValueError if evaluation fails.
    """
    if not formula:
        return source_value

    namespace: dict[str, Any] = {"source": source_value, **_SAFE_BUILTINS}
    try:
        return eval(formula, {"__builtins__": {}}, namespace)  # noqa: S307
    except Exception as exc:
        raise ValueError(
            f"Formula evaluation failed: {formula!r} with source={source_value!r}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Helpers for nested field access
# ---------------------------------------------------------------------------


def _get_nested(obj: Any, dotted_path: str) -> Any:
    """Retrieve a value from a nested object/dict using a dotted path.

    Supports both attribute access (Pydantic models) and dict key access.
    For example: ``_get_nested(spec, "dimensions.outer_diameter")``
    """
    parts = dotted_path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current[part]
        else:
            current = getattr(current, part)
    return current


def _set_nested(obj: Any, dotted_path: str, value: Any) -> None:
    """Set a value on a nested object/dict using a dotted path.

    Navigates to the parent and sets the final key/attribute.
    """
    parts = dotted_path.split(".")
    current = obj
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        else:
            current = getattr(current, part)

    final = parts[-1]
    if isinstance(current, dict):
        current[final] = value
    else:
        setattr(current, final, value)


def _extract_component_id(param_name: str) -> str:
    """Extract the component ID prefix from a fully-qualified parameter name.

    Convention: ``"component_id.field.subfield"`` -> ``"component_id"``.
    """
    return param_name.split(".")[0]


def _extract_field_path(param_name: str) -> str:
    """Extract the field path from a fully-qualified parameter name.

    Convention: ``"component_id.field.subfield"`` -> ``"field.subfield"``.
    """
    parts = param_name.split(".", 1)
    return parts[1] if len(parts) > 1 else ""


# ---------------------------------------------------------------------------
# CascadeEngine
# ---------------------------------------------------------------------------


class CascadeEngine:
    """Reactive change propagation engine.

    When a component changes, automatically propagates effects through
    the dependency graph to update affected components, BOM, and assembly.

    The engine is deterministic: given the same graph state and the same
    changes, it always produces the same result.  No randomness, no LLM
    calls -- pure computation.

    Usage::

        engine = CascadeEngine(registry, graph)
        # Register a dependency: when pole OD changes, bracket bore must follow
        engine.graph.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            "source + 0.2"   # clearance fit
        )
        result = engine.apply_change("pole", {"dimensions.outer_diameter": 35.0})
    """

    def __init__(
        self,
        registry: ComponentRegistry,
        graph: DependencyGraph,
    ) -> None:
        self.registry = registry
        self.graph = graph
        self._listeners: list[CascadeListener] = []

    # -- Listener management ------------------------------------------------

    def register_listener(self, listener: CascadeListener) -> None:
        """Register a listener for cascade events."""
        self._listeners.append(listener)

    def unregister_listener(self, listener: CascadeListener) -> None:
        """Unregister a previously registered listener."""
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    # -- Core cascade -------------------------------------------------------

    def apply_change(
        self, component_id: str, changes: dict[str, Any]
    ) -> CascadeResult:
        """Apply a change to a component and propagate through the dependency graph.

        Args:
            component_id: The component being changed (its registry ID).
            changes: Dict of field changes, e.g.
                ``{"dimensions.outer_diameter": 35.0, "mass_g": 120.0}``.

        Returns:
            CascadeResult with all affected components and their updates.

        Raises:
            KeyError: If the component is not in the registry.
        """
        spec = self.registry.get(component_id)
        if spec is None:
            raise KeyError(f"Component {component_id!r} not found in registry")

        result = CascadeResult(
            source_component=component_id,
            source_changes=dict(changes),
        )

        # Step 1: Apply changes to the source component
        for field_path, new_value in changes.items():
            try:
                old_value = _get_nested(spec, field_path)
            except (KeyError, AttributeError):
                old_value = None

            _set_nested(spec, field_path, new_value)

            # Track BOM/mass/cost flags on the source
            if "mass" in field_path:
                result.mass_changed = True
            if "cost" in field_path or "procurement" in field_path:
                result.cost_changed = True
                result.bom_changed = True

        # Re-register the (mutated) spec so the registry is consistent
        self.registry.add(spec)

        # Step 2: Detect downstream cascade for each changed parameter
        all_affected_params: list[str] = []
        seen: set[str] = set()
        for field_path in changes:
            qualified_param = f"{component_id}.{field_path}"
            cascade_params = self.graph.detect_cascade(qualified_param)
            for p in cascade_params:
                if p not in seen:
                    seen.add(p)
                    all_affected_params.append(p)

        if not all_affected_params:
            result.total_affected = 0
            self._notify_cascade_complete(result)
            return result

        # Step 3: Topological sort to determine evaluation order.
        # We only need the affected subset, but topological_sort gives us
        # the full graph order.  We filter to the affected set while
        # preserving topological ordering.
        try:
            full_order = self.graph.topological_sort()
        except ValueError as exc:
            logger.error("Cycle detected during cascade: %s", exc)
            # Return what we have; mark everything as failed
            for param in all_affected_params:
                cid = _extract_component_id(param)
                fp = _extract_field_path(param)
                result.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.FAILED,
                        formula="<cycle>",
                    )
                )
            result.total_affected = len(result.affected_components)
            self._notify_cascade_complete(result)
            return result

        affected_set = set(all_affected_params)
        ordered_affected = [p for p in full_order if p in affected_set]

        # Step 4: Evaluate each affected parameter in topological order
        for param in ordered_affected:
            cid = _extract_component_id(param)
            fp = _extract_field_path(param)

            target_spec = self.registry.get(cid)
            if target_spec is None:
                result.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.SKIPPED,
                    )
                )
                continue

            # Find the source edge(s) feeding this parameter
            source_params = self.graph.dependencies(param)
            if not source_params:
                result.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.SKIPPED,
                    )
                )
                continue

            # Use the first source (deterministic due to sorted dependencies)
            source_param = sorted(source_params)[0]
            source_cid = _extract_component_id(source_param)
            source_fp = _extract_field_path(source_param)

            edge = self.graph.get_edge(source_param, param)
            formula = edge.formula if edge else None

            # Get current source value from the (possibly already updated) registry
            source_spec = self.registry.get(source_cid)
            if source_spec is None:
                result.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.FAILED,
                        formula=formula or "",
                    )
                )
                continue

            try:
                source_value = _get_nested(source_spec, source_fp)
            except (KeyError, AttributeError):
                result.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.FAILED,
                        formula=formula or "",
                    )
                )
                continue

            # Get old value of the target
            try:
                old_value = _get_nested(target_spec, fp)
            except (KeyError, AttributeError):
                old_value = None

            # Evaluate formula
            try:
                new_value = _evaluate_formula(formula, source_value)
            except ValueError as exc:
                logger.warning(
                    "Formula evaluation failed for %s: %s", param, exc
                )
                result.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        old_value=old_value,
                        status=UpdateStatus.FAILED,
                        formula=formula or "",
                    )
                )
                continue

            # Apply the computed value
            try:
                _set_nested(target_spec, fp, new_value)
            except (KeyError, AttributeError, TypeError) as exc:
                logger.warning("Failed to set %s on %s: %s", fp, cid, exc)
                result.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        old_value=old_value,
                        new_value=new_value,
                        formula=formula or "",
                        status=UpdateStatus.FAILED,
                    )
                )
                continue

            # Re-register the updated spec
            self.registry.add(target_spec)

            affected = AffectedComponent(
                component_id=cid,
                field=fp,
                old_value=old_value,
                new_value=new_value,
                formula=formula or "",
                status=UpdateStatus.UPDATED,
            )
            result.affected_components.append(affected)

            # Track BOM/mass/cost changes
            if "mass" in fp:
                result.mass_changed = True
            if "cost" in fp or "procurement" in fp:
                result.cost_changed = True
                result.bom_changed = True

            # Notify listeners of this individual update
            self._notify_component_updated(
                cid, {fp: new_value}
            )

        result.total_affected = len(result.affected_components)

        # If any dimension changed on any component, the BOM may need updating
        # (e.g., mass recalculated from new volume)
        if any(
            "dimensions" in ac.field
            for ac in result.affected_components
            if ac.status == UpdateStatus.UPDATED
        ):
            result.bom_changed = True

        self._notify_cascade_complete(result)
        return result

    def preview_change(
        self, component_id: str, changes: dict[str, Any]
    ) -> CascadePreview:
        """Preview what a change would affect WITHOUT applying it.

        Creates a deep copy of affected specs to evaluate formulas, but
        does not modify the real registry.

        Args:
            component_id: The component being changed.
            changes: Dict of field changes.

        Returns:
            CascadePreview with all affected components and their projected updates.
        """
        spec = self.registry.get(component_id)
        if spec is None:
            raise KeyError(f"Component {component_id!r} not found in registry")

        # Work on a deep copy so we do not mutate the real spec
        spec_copy = spec.model_copy(deep=True)

        preview = CascadePreview(
            source_component=component_id,
            source_changes=dict(changes),
            applied=False,
        )

        # Apply changes to the copy
        for field_path, new_value in changes.items():
            try:
                _set_nested(spec_copy, field_path, new_value)
            except (KeyError, AttributeError):
                pass

            if "mass" in field_path:
                preview.mass_changed = True
            if "cost" in field_path or "procurement" in field_path:
                preview.cost_changed = True
                preview.bom_changed = True

        # Build a temporary value cache for formula evaluation in preview mode
        # Keys are qualified param names, values are the current (or updated) values.
        value_cache: dict[str, Any] = {}

        # Seed the cache with the source changes
        for field_path, new_value in changes.items():
            qualified = f"{component_id}.{field_path}"
            value_cache[qualified] = new_value

        # Detect downstream cascade
        all_affected_params: list[str] = []
        seen: set[str] = set()
        for field_path in changes:
            qualified_param = f"{component_id}.{field_path}"
            cascade_params = self.graph.detect_cascade(qualified_param)
            for p in cascade_params:
                if p not in seen:
                    seen.add(p)
                    all_affected_params.append(p)

        if not all_affected_params:
            preview.total_affected = 0
            return preview

        # Topological sort
        try:
            full_order = self.graph.topological_sort()
        except ValueError:
            for param in all_affected_params:
                cid = _extract_component_id(param)
                fp = _extract_field_path(param)
                preview.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.FAILED,
                        formula="<cycle>",
                    )
                )
            preview.total_affected = len(preview.affected_components)
            return preview

        affected_set = set(all_affected_params)
        ordered_affected = [p for p in full_order if p in affected_set]

        # Evaluate each affected parameter using the value cache (read-only)
        for param in ordered_affected:
            cid = _extract_component_id(param)
            fp = _extract_field_path(param)

            target_spec = self.registry.get(cid)
            if target_spec is None:
                preview.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.SKIPPED,
                    )
                )
                continue

            source_params = self.graph.dependencies(param)
            if not source_params:
                preview.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        status=UpdateStatus.SKIPPED,
                    )
                )
                continue

            source_param = sorted(source_params)[0]
            source_cid = _extract_component_id(source_param)
            source_fp = _extract_field_path(source_param)

            edge = self.graph.get_edge(source_param, param)
            formula = edge.formula if edge else None

            # Get source value from cache first, then from registry
            if source_param in value_cache:
                source_value = value_cache[source_param]
            else:
                source_spec = self.registry.get(source_cid)
                if source_spec is None:
                    preview.affected_components.append(
                        AffectedComponent(
                            component_id=cid,
                            field=fp,
                            status=UpdateStatus.FAILED,
                            formula=formula or "",
                        )
                    )
                    continue
                try:
                    source_value = _get_nested(source_spec, source_fp)
                except (KeyError, AttributeError):
                    preview.affected_components.append(
                        AffectedComponent(
                            component_id=cid,
                            field=fp,
                            status=UpdateStatus.FAILED,
                            formula=formula or "",
                        )
                    )
                    continue

            # Get old value
            try:
                old_value = _get_nested(target_spec, fp)
            except (KeyError, AttributeError):
                old_value = None

            # Evaluate formula
            try:
                new_value = _evaluate_formula(formula, source_value)
            except ValueError:
                preview.affected_components.append(
                    AffectedComponent(
                        component_id=cid,
                        field=fp,
                        old_value=old_value,
                        status=UpdateStatus.FAILED,
                        formula=formula or "",
                    )
                )
                continue

            # Store in cache for downstream parameters (but do NOT write to registry)
            value_cache[param] = new_value

            affected = AffectedComponent(
                component_id=cid,
                field=fp,
                old_value=old_value,
                new_value=new_value,
                formula=formula or "",
                status=UpdateStatus.UPDATED,
            )
            preview.affected_components.append(affected)

            if "mass" in fp:
                preview.mass_changed = True
            if "cost" in fp or "procurement" in fp:
                preview.cost_changed = True
                preview.bom_changed = True

        preview.total_affected = len(preview.affected_components)

        if any(
            "dimensions" in ac.field
            for ac in preview.affected_components
            if ac.status == UpdateStatus.UPDATED
        ):
            preview.bom_changed = True

        return preview

    def build_graph_from_registry(self) -> int:
        """Auto-detect dependencies from registry interface definitions.

        Scans all registered components for matching interface names.
        If component A has an interface named ``"pole_top"`` and component B
        also references ``"pole_top"`` with a matching diameter, they are
        likely mated and a dependency edge is added.

        Returns the number of edges added.
        """
        edges_added = 0
        all_specs = self.registry.list_all()

        # Build a map: interface_name -> list of (component_id, InterfacePoint)
        interface_map: dict[str, list[tuple[str, Any]]] = {}
        for spec in all_specs:
            for iname, ipoint in spec.interfaces.items():
                interface_map.setdefault(iname, []).append((spec.id, ipoint))

        # For each interface name with multiple components, create edges
        # between the components' dimension parameters.
        for iname, participants in interface_map.items():
            if len(participants) < 2:
                continue

            # Look for cylindrical interfaces where diameter should propagate
            for i, (cid_a, ipt_a) in enumerate(participants):
                for cid_b, ipt_b in participants[i + 1 :]:
                    if cid_a == cid_b:
                        continue

                    # If both have diameter_mm on this interface, create a
                    # dependency from the larger to the smaller (or equal).
                    if ipt_a.diameter_mm is not None and ipt_b.diameter_mm is not None:
                        source_param = f"{cid_a}.interfaces.{iname}.diameter_mm"
                        target_param = f"{cid_b}.interfaces.{iname}.diameter_mm"
                        if (source_param, target_param) not in [
                            (e.source, e.target) for e in self.graph.edges
                        ]:
                            self.graph.add_dependency(
                                source_param, target_param, formula="source"
                            )
                            edges_added += 1

        return edges_added

    # -- Private notification helpers ---------------------------------------

    def _notify_component_updated(
        self, component_id: str, changes: dict[str, Any]
    ) -> None:
        """Notify all listeners that a component was updated."""
        for listener in self._listeners:
            try:
                listener.on_component_updated(component_id, changes)
            except Exception:
                logger.exception(
                    "Listener %r failed in on_component_updated", listener
                )

    def _notify_cascade_complete(self, result: CascadeResult) -> None:
        """Notify all listeners that the cascade is complete."""
        for listener in self._listeners:
            try:
                listener.on_cascade_complete(result)
            except Exception:
                logger.exception(
                    "Listener %r failed in on_cascade_complete", listener
                )
