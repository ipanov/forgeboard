"""MCP tool definitions for ForgeBoard.

Each tool is a function decorated with ``@mcp.tool()`` from the FastMCP
server instance.  Tools delegate to the ForgeBoard Python API and return
plain dicts (JSON-serializable).  They never raise exceptions through
MCP -- errors are returned as ``{"error": "message"}`` dicts.

Tool naming convention: all tools use the ``forgeboard_`` prefix so they
are clearly namespaced in the AI assistant's tool list.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import asdict
from typing import Any

# Configure logging to stderr so it shows in the terminal running the MCP server
logging.basicConfig(
    level=logging.INFO,
    format="[ForgeBoard %(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("forgeboard.mcp")

from forgeboard.mcp_server.server import get_project, mcp, set_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe(fn):
    """Decorator that catches all exceptions and returns error dicts."""

    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs) if _is_coroutine(fn) else fn(*args, **kwargs)
        except Exception as exc:
            return {"error": str(exc)}

    # Preserve function metadata for FastMCP introspection
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    wrapper.__annotations__ = fn.__annotations__
    wrapper.__module__ = fn.__module__
    return wrapper


def _is_coroutine(fn) -> bool:
    """Check if a function is a coroutine function."""
    import asyncio
    return asyncio.iscoroutinefunction(fn)


def _spec_to_dict(spec) -> dict[str, Any]:
    """Convert a ComponentSpec to a JSON-serializable dict."""
    data = spec.model_dump(mode="json")
    return data


def _cascade_result_to_dict(result) -> dict[str, Any]:
    """Convert a CascadeResult dataclass to a JSON-serializable dict."""
    affected = []
    for ac in result.affected_components:
        affected.append({
            "component_id": ac.component_id,
            "field": ac.field,
            "old_value": _make_serializable(ac.old_value),
            "new_value": _make_serializable(ac.new_value),
            "formula": ac.formula,
            "status": ac.status.value if hasattr(ac.status, "value") else str(ac.status),
        })
    return {
        "source_component": result.source_component,
        "source_changes": result.source_changes,
        "affected_components": affected,
        "total_affected": result.total_affected,
        "bom_changed": result.bom_changed,
        "mass_changed": result.mass_changed,
        "cost_changed": result.cost_changed,
    }


def _preview_to_dict(preview) -> dict[str, Any]:
    """Convert a CascadePreview dataclass to a JSON-serializable dict."""
    result = _cascade_result_to_dict(preview)
    result["applied"] = getattr(preview, "applied", False)
    return result


def _make_serializable(value: Any) -> Any:
    """Ensure a value is JSON-serializable."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _make_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_serializable(v) for v in value]
    # Pydantic model
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    # Dataclass
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return str(value)


# ===========================================================================
# PROJECT MANAGEMENT TOOLS
# ===========================================================================


@mcp.tool()
def forgeboard_create_project(
    name: str,
    registry_path: str | None = None,
) -> dict:
    """Create or reset the ForgeBoard project.

    This must be called before any other tool.  Creates a new project
    with the given name.  If a registry_path is provided, components
    are loaded from that YAML file.

    Args:
        name: Project name (e.g. "Desk Lamp", "Drone Frame").
        registry_path: Optional path to a component registry YAML file.

    Returns:
        Project summary with component count and assembly count.
    """
    try:
        from forgeboard.core.project import ForgeProject

        project = ForgeProject(name, registry_path=registry_path)
        set_project(project)

        bom = project.get_bom()
        mass = project.get_mass_properties()

        return {
            "name": project.name,
            "component_count": len(project.registry),
            "assembly_count": len(project.assemblies),
            "total_mass_g": mass.total_mass_g,
            "total_cost": bom.total_cost,
            "status": "created",
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_get_project_summary() -> dict:
    """Get a summary of the current project state.

    Returns component count, assembly count, total mass, and total cost.
    Call this to check the current state before making changes.

    Returns:
        Project summary dict with counts and totals.
    """
    try:
        project = get_project()
        bom = project.get_bom()
        mass = project.get_mass_properties()

        return {
            "name": project.name,
            "component_count": len(project.registry),
            "assembly_count": len(project.assemblies),
            "total_mass_g": mass.total_mass_g,
            "total_cost": bom.total_cost,
            "components": [spec.id for spec in project.registry.list_all()],
            "assemblies": list(project.assemblies.keys()),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ===========================================================================
# COMPONENT TOOLS
# ===========================================================================


@mcp.tool()
def forgeboard_add_component(
    name: str,
    id: str,
    description: str = "",
    dimensions: dict | None = None,
    material: str | None = None,
    mass_g: float | None = None,
    is_cots: bool = False,
    interfaces: dict | None = None,
    procurement: dict | None = None,
    category: str = "uncategorized",
) -> dict:
    """Add a component to the project registry.

    Components are the building blocks of assemblies.  Each component
    has a unique ID, dimensions, optional material, and interface points
    for connecting to other components.

    Args:
        name: Human-readable component name (e.g. "Motor Bracket").
        id: Unique component ID (e.g. "PROJ-MECH-001").
        description: What this component does.
        dimensions: Key dimensions in mm (e.g. {"length": 42, "width": 30}).
        material: Material name (e.g. "Aluminum_6061").
        mass_g: Component mass in grams.
        is_cots: True if this is an off-the-shelf purchased part.
        interfaces: Named connection points as dict of name -> properties.
        procurement: Procurement details (supplier, unit_cost, url, etc.).
        category: Grouping category (structure, electronics, sensors, etc.).

    Returns:
        The created component specification as a dict.
    """
    try:
        from forgeboard.core.types import (
            ComponentSpec,
            InterfacePoint,
            Material,
        )

        project = get_project()

        # Build material if provided
        mat = None
        if material:
            mat = Material(name=material, density_g_cm3=1.0)

        # Build interfaces if provided
        iface_points: dict[str, InterfacePoint] = {}
        if interfaces:
            for iname, idata in interfaces.items():
                if isinstance(idata, dict):
                    iface_points[iname] = InterfacePoint(
                        name=idata.get("name", iname),
                        diameter_mm=idata.get("diameter_mm"),
                    )
                else:
                    iface_points[iname] = InterfacePoint(name=iname)

        spec = ComponentSpec(
            name=name,
            id=id,
            description=description,
            category=category,
            material=mat,
            dimensions=dimensions or {},
            interfaces=iface_points,
            mass_g=mass_g,
            is_cots=is_cots,
            procurement=procurement or {},
        )

        project.add_component(spec)

        return _spec_to_dict(spec)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_update_component(
    component_id: str,
    changes: dict,
) -> dict:
    """Update a component and trigger cascade propagation.

    When you change a component parameter, all downstream components
    connected via dependency formulas are automatically updated.  For
    example, changing a pole diameter will cascade to update the bracket
    bore diameter.

    Args:
        component_id: ID of the component to modify.
        changes: Dict of field changes, using dotted paths.
                 Example: {"dimensions.outer_diameter": 35.0, "mass_g": 120.0}

    Returns:
        Cascade result showing all affected downstream components
        and their updated values.
    """
    try:
        project = get_project()
        result = project.update_component(component_id, changes)
        return _cascade_result_to_dict(result)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_remove_component(component_id: str) -> dict:
    """Remove a component from the project registry.

    Args:
        component_id: ID of the component to remove.

    Returns:
        Success status and the removed component ID.
    """
    try:
        project = get_project()
        removed = project.remove_component(component_id)
        if removed:
            return {"status": "removed", "component_id": component_id}
        else:
            return {"error": f"Component '{component_id}' not found in registry"}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_get_component(component_id: str) -> dict:
    """Get the full specification of a component.

    Args:
        component_id: ID of the component to look up.

    Returns:
        Complete component specification as a dict, or error if not found.
    """
    try:
        project = get_project()
        spec = project.get_component(component_id)
        if spec is None:
            return {"error": f"Component '{component_id}' not found"}
        return _spec_to_dict(spec)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_list_components(category: str | None = None) -> dict:
    """List all components in the project, optionally filtered by category.

    Args:
        category: If provided, only list components in this category.

    Returns:
        List of component summaries (id, name, category, mass_g, is_cots).
    """
    try:
        project = get_project()

        if category:
            specs = project.registry.list_by_category(category)
        else:
            specs = project.registry.list_all()

        components = []
        for spec in specs:
            components.append({
                "id": spec.id,
                "name": spec.name,
                "category": spec.category,
                "mass_g": spec.mass_g,
                "is_cots": spec.is_cots,
                "dimension_count": len(spec.dimensions),
                "interface_count": len(spec.interfaces),
            })

        return {
            "count": len(components),
            "components": components,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ===========================================================================
# ASSEMBLY TOOLS
# ===========================================================================


@mcp.tool()
def forgeboard_create_assembly(name: str) -> dict:
    """Create a new assembly in the project.

    An assembly is a collection of component instances positioned
    relative to each other using geometric constraints.

    Args:
        name: Assembly name (e.g. "Main Frame", "Sensor Head").

    Returns:
        Assembly creation confirmation with the assembly name.
    """
    try:
        project = get_project()
        project.add_assembly(name)
        return {
            "status": "created",
            "assembly_name": name,
            "total_assemblies": len(project.assemblies),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_add_to_assembly(
    assembly_name: str,
    component_id: str,
    instance_name: str,
    at_origin: bool = False,
    constraints: list[dict] | None = None,
) -> dict:
    """Add a component instance to an assembly with optional constraints.

    The first part should be placed at_origin=True as the assembly datum.
    Subsequent parts are positioned using constraints that reference
    interface points on already-placed parts.

    Args:
        assembly_name: Name of the assembly to add to.
        component_id: ID of the component in the registry.
        instance_name: Unique instance name within this assembly.
        at_origin: If True, fix this part at the assembly origin.
        constraints: List of constraint dicts. Each constraint has:
            - type: "mate", "flush", "align", "offset", or "angle"
            - interface_a: Interface name on the reference part
            - interface_b: Interface name on this part
            - offset_mm: (optional) For offset constraints
            - angle_deg: (optional) For angle constraints

    Returns:
        Confirmation of the placement with assembly part count.
    """
    try:
        project = get_project()
        assembly = project.get_assembly(assembly_name)
        if assembly is None:
            return {"error": f"Assembly '{assembly_name}' not found"}

        spec = project.get_component(component_id)
        if spec is None:
            return {"error": f"Component '{component_id}' not found in registry"}

        # Build constraint objects
        from forgeboard.assembly.constraints import (
            Align,
            Angle,
            Flush,
            Mate,
            Offset,
        )

        constraint_objects = []
        if constraints:
            for c in constraints:
                c_type = c.get("type", "mate").lower()
                iface_a = c.get("interface_a", "")
                iface_b = c.get("interface_b", "")

                if c_type == "mate":
                    constraint_objects.append(Mate(iface_a, iface_b))
                elif c_type == "flush":
                    constraint_objects.append(Flush(iface_a, iface_b))
                elif c_type == "align":
                    constraint_objects.append(Align(iface_a, iface_b))
                elif c_type == "offset":
                    constraint_objects.append(
                        Offset(iface_a, iface_b, distance_mm=c.get("offset_mm", 0.0))
                    )
                elif c_type == "angle":
                    constraint_objects.append(
                        Angle(iface_a, iface_b, angle_deg=c.get("angle_deg", 0.0))
                    )
                else:
                    return {"error": f"Unknown constraint type: {c_type}"}

        # Create a bounding-box proxy shape for dry-fit validation.
        # If the component has length/width/height dimensions, we generate
        # real geometry so the solver can check collisions and clearances.
        # If dimensions are missing, we fall back to a null placeholder.
        from forgeboard.engines.base import Shape

        shape = Shape(native=None, name=instance_name)
        if spec.mass_g is not None:
            shape.mass_kg = spec.mass_g / 1000.0

        # Store dimensions in metadata for deferred bounding-box creation
        if spec.dimensions:
            shape.metadata["_dimensions"] = dict(spec.dimensions)
            shape.metadata["_component_id"] = component_id

        assembly.add_part(
            name=instance_name,
            shape=shape,
            at_origin=at_origin,
            constraints=constraint_objects or None,
            interfaces=dict(spec.interfaces) if spec.interfaces else None,
        )

        return {
            "status": "added",
            "assembly_name": assembly_name,
            "instance_name": instance_name,
            "component_id": component_id,
            "at_origin": at_origin,
            "constraint_count": len(constraint_objects),
            "total_parts": len(assembly._parts),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_solve_assembly(assembly_name: str, skip_collisions: bool = False) -> dict:
    """Solve constraint positions and run collision detection.

    This is the key validation tool.  It solves all geometric constraints
    to determine part positions, then checks for physical collisions and
    clearance violations.

    Args:
        assembly_name: Name of the assembly to solve.
        skip_collisions: If True, skip expensive pairwise collision detection.
            Use this for fast dry-fit layout validation where you only need
            to verify that constraints resolve and parts have positions.

    Returns:
        Placement results, collisions (with severity), clearance
        violations, and overall validation status.
    """
    try:
        import time as _time
        _t0 = _time.perf_counter()
        logger.info("solve_assembly(%s, skip_collisions=%s) — starting", assembly_name, skip_collisions)

        project = get_project()
        assembly = project.get_assembly(assembly_name)
        if assembly is None:
            return {"error": f"Assembly '{assembly_name}' not found"}

        logger.info("  Assembly has %d parts", len(assembly._parts))

        # Use the Build123d engine for solving if no real engine is set
        engine = project.engine
        if engine is None:
            from forgeboard.engines.build123d_engine import Build123dEngine
            engine = Build123dEngine()
            logger.info("  Created Build123dEngine")

        logger.info("  Calling assembly.solve(skip_collisions=%s)...", skip_collisions)
        try:
            solved = assembly.solve(engine, skip_collisions=skip_collisions)
        except Exception as solve_err:
            _t1 = _time.perf_counter()
            logger.error("  solve() FAILED after %.2fs: %s", _t1 - _t0, solve_err)
            logger.error("  Traceback: %s", traceback.format_exc())
            return {"error": f"solve() failed after {_t1 - _t0:.1f}s: {solve_err}",
                    "traceback": traceback.format_exc()}
        _t1 = _time.perf_counter()
        logger.info("  solve() completed in %.2fs — %d parts solved, %d collisions",
                     _t1 - _t0, len(solved.parts), len(solved.collisions))

        # Build placements dict
        placements = {}
        for name, sp in solved.parts.items():
            placements[name] = {
                "position": {
                    "x": sp.placement.position.x,
                    "y": sp.placement.position.y,
                    "z": sp.placement.position.z,
                },
                "rotation_axis": {
                    "x": sp.placement.rotation_axis.x,
                    "y": sp.placement.rotation_axis.y,
                    "z": sp.placement.rotation_axis.z,
                },
                "rotation_angle_deg": sp.placement.rotation_angle_deg,
            }

        # Build collisions list
        collisions = []
        for col in solved.collisions:
            collisions.append({
                "part_a": col.part_a,
                "part_b": col.part_b,
                "volume_mm3": col.volume_mm3,
                "severity": col.severity.value,
            })

        # Build clearance violations list
        clearance_violations = []
        for cv in solved.clearance_violations:
            clearance_violations.append({
                "part_a": cv.part_a,
                "part_b": cv.part_b,
                "actual_gap_mm": cv.actual_gap_mm,
                "required_gap_mm": cv.required_gap_mm,
            })

        return {
            "assembly_name": solved.name,
            "part_count": solved.part_count,
            "placements": placements,
            "collisions": collisions,
            "collision_count": len(collisions),
            "clearance_violations": clearance_violations,
            "clearance_violation_count": len(clearance_violations),
            "has_collisions": solved.has_collisions,
            "is_valid": solved.is_valid,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_validate_assembly(assembly_name: str) -> dict:
    """Run the full validation pipeline on an assembly.

    Goes beyond solve_assembly by running additional checks:
    collision detection, clearance verification, floating parts
    detection, and mass budget validation.

    Args:
        assembly_name: Name of the assembly to validate.

    Returns:
        Detailed validation report with collisions, clearance violations,
        floating parts, mass budget check, and overall pass/fail.
    """
    try:
        project = get_project()
        assembly = project.get_assembly(assembly_name)
        if assembly is None:
            return {"error": f"Assembly '{assembly_name}' not found"}

        engine = project.engine
        if engine is None:
            from forgeboard.engines.build123d_engine import Build123dEngine
            engine = Build123dEngine()

        solved = assembly.solve(engine)

        # Build collisions
        collisions = []
        for col in solved.collisions:
            collisions.append({
                "part_a": col.part_a,
                "part_b": col.part_b,
                "volume_mm3": col.volume_mm3,
                "severity": col.severity.value,
            })

        # Build clearance violations
        clearance_violations = []
        for cv in solved.clearance_violations:
            clearance_violations.append({
                "part_a": cv.part_a,
                "part_b": cv.part_b,
                "actual_gap_mm": cv.actual_gap_mm,
                "required_gap_mm": cv.required_gap_mm,
            })

        # Detect floating parts (parts not connected to anything via constraints)
        floating_parts = []
        for name in assembly._order:
            entry = assembly._parts[name]
            if not entry.at_origin and not entry.constraints:
                # Check global constraints too
                has_global = any(
                    b == name for _, b, _ in assembly._global_constraints
                )
                if not has_global:
                    floating_parts.append(name)

        # Mass budget
        total_mass_g = 0.0
        per_part_mass = {}
        for name, sp in solved.parts.items():
            mass = (sp.shape.mass_kg or 0.0) * 1000.0
            per_part_mass[name] = mass
            total_mass_g += mass

        passed = (
            not solved.has_collisions
            and len(clearance_violations) == 0
            and len(floating_parts) == 0
        )

        return {
            "assembly_name": solved.name,
            "passed": passed,
            "part_count": solved.part_count,
            "collisions": collisions,
            "collision_count": len(collisions),
            "clearance_violations": clearance_violations,
            "clearance_violation_count": len(clearance_violations),
            "floating_parts": floating_parts,
            "floating_part_count": len(floating_parts),
            "total_mass_g": total_mass_g,
            "per_part_mass_g": per_part_mass,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ===========================================================================
# PROCUREMENT TOOLS
# ===========================================================================


@mcp.tool()
def forgeboard_search_cots(
    query: str,
    category: str | None = None,
    country: str | None = None,
) -> dict:
    """Search for off-the-shelf components from supplier databases.

    Searches across registered supplier providers, ordered by geographic
    proximity (local suppliers first, then regional, then global).

    Args:
        query: Search description (e.g. "M5x12 socket head cap screw").
        category: Optional category filter (e.g. "fasteners", "motors").
        country: ISO country code for location-aware ordering (default: "US").

    Returns:
        List of matching products with prices, suppliers, and availability.
    """
    try:
        from forgeboard.procure.registry import ProviderRegistry

        user_country = country or "US"
        registry = ProviderRegistry(user_country=user_country)

        matches = registry.search_all(query, category=category)

        results = []
        for m in matches:
            results.append({
                "product_id": m.product_id,
                "name": m.name,
                "description": m.description,
                "supplier": m.supplier,
                "price": m.price,
                "currency": m.currency,
                "url": m.url,
                "in_stock": m.in_stock,
                "lead_time_days": m.lead_time_days,
                "confidence": m.confidence,
            })

        return {
            "query": query,
            "match_count": len(results),
            "matches": results,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_buy_or_build(component_id: str) -> dict:
    """Evaluate whether a component should be purchased or custom-made.

    Uses a deterministic rule tree for well-known component types
    (fasteners, motors, electronics, sensors) and falls back to
    supplier search for ambiguous cases.

    Args:
        component_id: ID of the component to evaluate.

    Returns:
        Decision (BUY, BUILD, or EITHER) with confidence score,
        reasoning, and any matching products found.
    """
    try:
        from forgeboard.procure.registry import ProviderRegistry
        from forgeboard.procure.researcher import COTSResearcher

        project = get_project()
        spec = project.get_component(component_id)
        if spec is None:
            return {"error": f"Component '{component_id}' not found"}

        registry = ProviderRegistry()
        researcher = COTSResearcher(registry)
        decision = researcher.should_buy_or_build(spec)

        matches = []
        for m in decision.matches:
            matches.append({
                "product_id": m.product_id,
                "name": m.name,
                "supplier": m.supplier,
                "price": m.price,
                "currency": m.currency,
                "in_stock": m.in_stock,
                "confidence": m.confidence,
            })

        return {
            "component_id": component_id,
            "component_name": spec.name,
            "decision": decision.decision.value,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "estimated_buy_cost": decision.estimated_buy_cost,
            "estimated_build_cost": decision.estimated_build_cost,
            "matches": matches,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ===========================================================================
# EXPORT TOOLS
# ===========================================================================


@mcp.tool()
def forgeboard_export_step(
    assembly_name: str,
    output_path: str,
) -> dict:
    """Export an assembly as a STEP file.

    The assembly must have been solved first.  All parts are fused into
    a single compound and written to the specified file path.

    Args:
        assembly_name: Name of the assembly to export.
        output_path: File path for the STEP output (e.g. "output/frame.step").

    Returns:
        Path to the exported file and part count.
    """
    try:
        from pathlib import Path

        from forgeboard.export.step_export import export_assembly_step

        project = get_project()
        assembly = project.get_assembly(assembly_name)
        if assembly is None:
            return {"error": f"Assembly '{assembly_name}' not found"}

        engine = project.engine
        if engine is None:
            from forgeboard.engines.build123d_engine import Build123dEngine
            engine = Build123dEngine()

        solved = assembly.solve(engine)
        result_path = export_assembly_step(solved, output_path, engine)

        return {
            "status": "exported",
            "format": "STEP",
            "path": str(result_path),
            "part_count": solved.part_count,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_export_stl(
    assembly_name: str,
    output_path: str,
) -> dict:
    """Export an assembly as an STL file.

    The assembly must have been solved first.  All parts are fused and
    written as an STL mesh to the specified file path.

    Args:
        assembly_name: Name of the assembly to export.
        output_path: File path for the STL output (e.g. "output/frame.stl").

    Returns:
        Path to the exported file and part count.
    """
    try:
        from forgeboard.assembly.orchestrator import Assembly

        project = get_project()
        assembly = project.get_assembly(assembly_name)
        if assembly is None:
            return {"error": f"Assembly '{assembly_name}' not found"}

        engine = project.engine
        if engine is None:
            from forgeboard.engines.build123d_engine import Build123dEngine
            engine = Build123dEngine()

        solved = assembly.solve(engine)
        Assembly.export(solved, engine, output_path, fmt="stl")

        return {
            "status": "exported",
            "format": "STL",
            "path": output_path,
            "part_count": solved.part_count,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_render_views(
    assembly_name: str,
    output_dir: str,
    views: list[str] | None = None,
) -> dict:
    """Render SVG orthographic views of an assembly.

    Generates SVG files for each requested view angle.

    Args:
        assembly_name: Name of the assembly to render.
        output_dir: Directory to save rendered SVG files.
        views: List of view angles. Default: ["front", "right", "top", "iso"].

    Returns:
        List of generated file paths.
    """
    try:
        from pathlib import Path

        from forgeboard.assembly.orchestrator import Assembly

        project = get_project()
        assembly = project.get_assembly(assembly_name)
        if assembly is None:
            return {"error": f"Assembly '{assembly_name}' not found"}

        engine = project.engine
        if engine is None:
            from forgeboard.engines.build123d_engine import Build123dEngine
            engine = Build123dEngine()

        solved = assembly.solve(engine)

        view_list = views or ["front", "right", "top", "iso"]
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        generated_files = []
        for view in view_list:
            out_path = str(out_dir / f"{assembly_name}_{view}.svg")
            try:
                Assembly.export(solved, engine, out_path, fmt="svg")
                generated_files.append(out_path)
            except Exception as view_exc:
                generated_files.append({"view": view, "error": str(view_exc)})

        return {
            "status": "rendered",
            "assembly_name": assembly_name,
            "output_dir": output_dir,
            "files": generated_files,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_generate_bom(
    assembly_name: str | None = None,
    format: str = "json",
) -> dict:
    """Generate a bill of materials for the project or a specific assembly.

    If assembly_name is provided, generates BOM from that assembly.
    Otherwise, generates a flat BOM from all registered components.

    Args:
        assembly_name: Optional assembly name. If None, uses all components.
        format: Output format -- "json", "csv", or "markdown".

    Returns:
        BOM data with parts, quantities, materials, masses, costs,
        and supplier information.
    """
    try:
        project = get_project()
        bom = project.get_bom()

        entries = []
        for entry in bom.entries:
            entries.append({
                "part_name": entry.part_name,
                "part_id": entry.part_id,
                "quantity": entry.quantity,
                "material": entry.material,
                "mass_g": entry.mass_g,
                "unit_cost": entry.unit_cost,
                "total_cost": entry.total_cost,
                "supplier": entry.supplier,
                "is_cots": entry.is_cots,
                "manufacturing_method": entry.manufacturing_method,
            })

        result: dict[str, Any] = {
            "total_entries": len(entries),
            "total_mass_g": bom.total_mass_g,
            "total_cost": bom.total_cost,
            "currency": bom.currency,
            "cots_count": bom.cots_count,
            "custom_count": bom.custom_count,
            "fastener_count": bom.fastener_count,
        }

        if format == "json":
            result["entries"] = entries
        elif format == "markdown":
            result["markdown"] = bom.summary()
        elif format == "csv":
            # Generate CSV string
            lines = ["part_name,part_id,quantity,material,mass_g,unit_cost,total_cost,supplier,is_cots"]
            for e in entries:
                mass_str = f"{e['mass_g']:.1f}" if e["mass_g"] is not None else ""
                unit_str = f"{e['unit_cost']:.2f}" if e["unit_cost"] is not None else ""
                total_str = f"{e['total_cost']:.2f}" if e["total_cost"] is not None else ""
                lines.append(
                    f"{e['part_name']},{e['part_id']},{e['quantity']},"
                    f"{e['material']},{mass_str},{unit_str},{total_str},"
                    f"{e['supplier']},{e['is_cots']}"
                )
            result["csv"] = "\n".join(lines)
        else:
            return {"error": f"Unknown format: {format}. Use 'json', 'csv', or 'markdown'."}

        return result
    except Exception as exc:
        return {"error": str(exc)}


# ===========================================================================
# DESIGN TOOLS
# ===========================================================================


@mcp.tool()
def forgeboard_analyze_sketch(
    image_path: str,
    description: str | None = None,
) -> dict:
    """Analyze a sketch image to extract components and dimensions.

    Uses vision AI to identify components, dimensions, materials, and
    assembly relationships from a hand-drawn or CAD sketch.

    Args:
        image_path: Path to the sketch image file (PNG, JPEG, etc.).
        description: Optional text description to provide additional context.

    Returns:
        Identified components, dimensions, materials, relationships,
        and ambiguities that need clarification.
    """
    try:
        from forgeboard.design.analyzer import DesignAnalyzer
        from forgeboard.design.llm_provider import MockProvider

        # Use mock provider by default; real provider requires API key
        llm = MockProvider()
        analyzer = DesignAnalyzer(llm)

        result = analyzer.analyze_sketch(image_path, description=description or "")

        components = []
        for comp in result.identified_components:
            components.append({
                "name": comp.name,
                "shape_description": comp.shape_description,
                "estimated_dimensions": comp.estimated_dimensions,
                "interfaces": comp.interfaces,
                "is_cots_candidate": comp.is_cots_candidate,
                "confidence": comp.confidence,
            })

        relationships = []
        for rel in result.assembly_relationships:
            relationships.append({
                "part_a": rel.part_a,
                "part_b": rel.part_b,
                "relationship": rel.relationship,
            })

        return {
            "components": components,
            "detected_dimensions": result.detected_dimensions,
            "detected_materials": result.detected_materials,
            "assembly_relationships": relationships,
            "ambiguities": result.ambiguities,
            "confidence_score": result.confidence_score,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_analyze_text(description: str) -> dict:
    """Analyze a text description to extract components and design intent.

    Parses a natural-language description of a part or assembly to
    identify components, constraints, materials, and missing information
    that needs to be specified.

    Args:
        description: Natural-language description of the design.
                     Example: "L-bracket for NEMA 17 motor, 3mm aluminum,
                     four M3 mounting holes"

    Returns:
        Extracted components, constraints, materials, and list of
        missing information needed for full specification.
    """
    try:
        from forgeboard.design.analyzer import DesignAnalyzer
        from forgeboard.design.llm_provider import MockProvider

        llm = MockProvider()
        analyzer = DesignAnalyzer(llm)

        result = analyzer.analyze_text(description)

        components = []
        for comp in result.components:
            components.append({
                "name": comp.name,
                "shape_description": comp.shape_description,
                "estimated_dimensions": comp.estimated_dimensions,
                "interfaces": comp.interfaces,
                "is_cots_candidate": comp.is_cots_candidate,
                "confidence": comp.confidence,
            })

        return {
            "components": components,
            "constraints": result.constraints,
            "materials": result.materials,
            "missing_info": result.missing_info,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ===========================================================================
# DEPENDENCY / CASCADE TOOLS
# ===========================================================================


@mcp.tool()
def forgeboard_preview_change(
    component_id: str,
    changes: dict,
) -> dict:
    """Preview what would change without actually applying the changes.

    Shows all downstream components that would be affected by a parameter
    change, without modifying the registry.  Use this to check the impact
    before committing a change.

    Args:
        component_id: ID of the component to preview changes for.
        changes: Dict of field changes (same format as update_component).

    Returns:
        Preview of affected components and their projected new values.
    """
    try:
        project = get_project()
        preview = project.preview_update(component_id, changes)
        return _preview_to_dict(preview)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_add_dependency(
    source: str,
    target: str,
    formula: str | None = None,
) -> dict:
    """Add a dependency between two component parameters.

    When the source parameter changes, the target parameter is
    automatically updated using the formula.  The formula uses
    "source" as the variable name for the source value.

    Args:
        source: Fully-qualified source parameter.
                Example: "pole.dimensions.outer_diameter"
        target: Fully-qualified target parameter.
                Example: "bracket.dimensions.inner_diameter"
        formula: Python expression using "source" variable.
                 Example: "source + 0.2" (clearance fit).
                 If None, target receives the same value as source.

    Returns:
        Confirmation of the dependency creation.
    """
    try:
        project = get_project()
        project.graph.add_dependency(source, target, formula=formula)

        return {
            "status": "created",
            "source": source,
            "target": target,
            "formula": formula or "source",
            "total_edges": len(project.graph.edges),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Manufacturing tools
# ---------------------------------------------------------------------------


@mcp.tool()
def forgeboard_configure_manufacturing(
    user_location: str = "",
    labor_rate_per_hour: float = 30.0,
    overhead_rate: float = 0.15,
) -> dict:
    """Configure the project's manufacturing settings.

    Sets the user's location (for local-first service bureau search),
    labor rate, and overhead multiplier.  Call this before estimating
    manufacturing costs for custom parts.

    Args:
        user_location: User's location for local-first search.
                       Example: "Skopje, MK"
        labor_rate_per_hour: Labor cost in USD/hour (default 30).
        overhead_rate: Overhead multiplier (default 0.15 = 15%).

    Returns:
        Confirmation with current config.
    """
    try:
        from forgeboard.manufacturing.estimator import ProjectManufacturingConfig

        project = get_project()
        # Parse "City, CC" format into country + city
        country = ""
        city = ""
        if user_location:
            parts = [p.strip() for p in user_location.split(",")]
            if len(parts) >= 2:
                city = parts[0]
                country = parts[1]
            else:
                city = parts[0]

        config = ProjectManufacturingConfig(
            user_country=country,
            user_city=city,
            labor_rate_per_hour=labor_rate_per_hour,
            overhead_rate=overhead_rate,
        )
        project.set_manufacturing_config(config)

        return {
            "status": "configured",
            "user_country": country,
            "user_city": city,
            "labor_rate_per_hour": labor_rate_per_hour,
            "overhead_rate": overhead_rate,
            "tools_count": len(config.owned_tools),
            "materials_count": len(config.available_materials),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_add_manufacturing_tool(
    tool_id: str,
    name: str,
    tool_type: str,
    purchase_cost: float = 0.0,
    expected_lifetime_hours: float = 5000.0,
    maintenance_cost_per_hour: float = 0.0,
    power_cost_per_hour: float = 0.0,
    compatible_materials: list[str] | None = None,
    build_envelope_mm: dict[str, float] | None = None,
) -> dict:
    """Register a manufacturing tool the user owns.

    This is totally generic -- any type of fabrication equipment.
    The tool_type maps to a manufacturing method ID (e.g. "additive",
    "subtractive", "sheet_fabrication", etc.).

    Args:
        tool_id: Unique identifier for this tool.
        name: Human-readable name (e.g. "Prusa MK4", "Haas VF-2").
        tool_type: Manufacturing method ID this tool performs.
        purchase_cost: Purchase price for amortization calculation.
        expected_lifetime_hours: Expected total operating hours.
        maintenance_cost_per_hour: Hourly maintenance cost.
        power_cost_per_hour: Hourly power cost.
        compatible_materials: List of material IDs this tool can use.
        build_envelope_mm: Max dimensions dict (x_max, y_max, z_max).

    Returns:
        Tool details including computed hourly rate.
    """
    try:
        from forgeboard.manufacturing.types import ManufacturingTool

        project = get_project()
        if project.manufacturing_config is None:
            return {"error": "Call forgeboard_configure_manufacturing first"}

        tool = ManufacturingTool(
            id=tool_id,
            name=name,
            tool_type=tool_type,
            purchase_cost=purchase_cost,
            expected_lifetime_hours=expected_lifetime_hours,
            maintenance_cost_per_hour=maintenance_cost_per_hour,
            power_cost_per_hour=power_cost_per_hour,
            compatible_materials=compatible_materials or [],
            build_envelope_mm=build_envelope_mm or {},
        )
        project.manufacturing_config.owned_tools.append(tool)
        project._manufacturing_estimator = None

        return {
            "status": "added",
            "tool_id": tool_id,
            "name": name,
            "tool_type": tool_type,
            "hourly_rate": round(tool.total_hourly_rate, 4),
            "amortization_per_hour": round(tool.amortization_per_hour, 4),
            "total_tools": len(project.manufacturing_config.owned_tools),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_add_raw_material(
    material_id: str,
    name: str,
    material_type: str,
    cost_per_unit: float,
    unit: str = "kg",
    density_g_cm3: float = 0.0,
    compatible_methods: list[str] | None = None,
    supplier: str = "",
) -> dict:
    """Register a raw material available for manufacturing.

    Args:
        material_id: Unique identifier (e.g. "pla_white", "al6061_plate").
        name: Human-readable name.
        material_type: Type category (e.g. "filament", "plate", "sheet").
        cost_per_unit: Cost per unit of measure.
        unit: Unit of measure (e.g. "kg", "m", "m2", "L").
        density_g_cm3: Material density for volume/mass conversion.
        compatible_methods: Method IDs this material works with.
        supplier: Supplier name.

    Returns:
        Material registration confirmation.
    """
    try:
        from forgeboard.manufacturing.types import RawMaterial

        project = get_project()
        if project.manufacturing_config is None:
            return {"error": "Call forgeboard_configure_manufacturing first"}

        material = RawMaterial(
            id=material_id,
            name=name,
            material_type=material_type,
            cost_per_unit=cost_per_unit,
            unit=unit,
            density_g_cm3=density_g_cm3,
            compatible_methods=compatible_methods or [],
            supplier=supplier,
        )
        project.manufacturing_config.available_materials.append(material)
        project._manufacturing_estimator = None

        return {
            "status": "added",
            "material_id": material_id,
            "name": name,
            "cost_per_unit": cost_per_unit,
            "unit": unit,
            "total_materials": len(project.manufacturing_config.available_materials),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def forgeboard_estimate_manufacturing_cost(
    component_id: str,
    method: str | None = None,
    volume_cm3: float = 0.0,
    estimated_time_hours: float = 0.0,
) -> dict:
    """Estimate the manufacturing cost for a custom component.

    Walks the fallback chain: in-house tool -> local service ->
    online service -> LLM estimate.

    Args:
        component_id: ID of the component to estimate.
        method: Manufacturing method ID (auto-inferred from material if omitted).
        volume_cm3: Part volume (from geometry or mesh).  If 0, estimated from mass.
        estimated_time_hours: Estimated fabrication time.  If 0, estimated from volume.

    Returns:
        Manufacturing quote with cost breakdown and source.
    """
    try:
        from forgeboard.manufacturing.estimator import infer_method_from_material
        from forgeboard.manufacturing.types import PartGeometry

        project = get_project()
        spec = project.get_component(component_id)
        if spec is None:
            return {"error": f"Component {component_id!r} not found"}

        if spec.is_cots:
            unit_cost = 0.0
            supplier = ""
            if spec.procurement:
                unit_cost = float(spec.procurement.get("unit_cost", 0))
                supplier = str(spec.procurement.get("supplier", ""))
            return {
                "source": "procurement",
                "total_cost": unit_cost,
                "supplier": supplier,
                "confidence": 1.0,
                "notes": "COTS component - procurement cost",
            }

        estimator = project.get_manufacturing_estimator()
        if estimator is None:
            return {"error": "No manufacturing config. Call forgeboard_configure_manufacturing first."}

        method_id = method
        if method_id is None:
            mat_name = spec.material.name if spec.material else ""
            method_id = infer_method_from_material(mat_name)
        if method_id is None:
            mfg = str(spec.metadata.get("manufacturing_method", ""))
            method_id = mfg.lower() if mfg else "unknown"

        vol = volume_cm3
        if vol <= 0 and spec.mass_g and spec.material and spec.material.density_g_cm3 > 0:
            vol = spec.mass_g / spec.material.density_g_cm3

        geometry = PartGeometry(
            volume_cm3=vol,
            estimated_print_time_hours=estimated_time_hours,
            estimated_machining_time_hours=estimated_time_hours,
        )

        mat_name = spec.material.name if spec.material else ""
        quote = estimator.estimate_with_fallback(method_id, mat_name, geometry)
        if quote is None:
            return {
                "error": "No estimate available from any source",
                "method": method_id,
                "material": mat_name,
                "volume_cm3": vol,
            }

        return {
            "total_cost": quote.total_cost,
            "material_cost": quote.material_cost,
            "tool_cost": quote.tool_cost,
            "labor_cost": quote.labor_cost,
            "overhead_cost": quote.overhead_cost,
            "method": quote.method,
            "material": quote.material,
            "source": quote.source,
            "source_name": quote.source_name,
            "confidence": quote.confidence,
            "lead_time_days": quote.lead_time_days,
            "notes": quote.notes,
        }
    except Exception as exc:
        return {"error": str(exc)}
