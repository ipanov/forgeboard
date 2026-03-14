"""Manufacturing cost estimation heuristics.

Provides simple rule-based cost estimates for common manufacturing
methods.  These are rough order-of-magnitude figures suitable for early
design-phase trade studies, not production quoting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from forgeboard.core.types import ComponentSpec, Material


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Breakdown of estimated manufacturing cost for a single component.

    Attributes:
        material_cost: Raw material cost in USD.
        manufacturing_cost: Fabrication / processing cost in USD.
        total_cost: material_cost + manufacturing_cost.
        method: Manufacturing method used for the estimate.
        notes: Human-readable explanation of how the estimate was derived.
    """

    material_cost: float
    manufacturing_cost: float
    total_cost: float
    method: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Heuristic constants
# ---------------------------------------------------------------------------

# FDM 3D printing cost factors
_FDM_MARKUP: float = 1.3  # material waste + support markup
_FDM_MACHINE_RATE_PER_CM3: float = 0.15  # USD per cm3 machine time

# SLA / SLS printing cost factors
_SLA_MARKUP: float = 1.5
_SLA_MACHINE_RATE_PER_CM3: float = 0.50

_SLS_MARKUP: float = 1.4
_SLS_MACHINE_RATE_PER_CM3: float = 0.40

# CNC machining cost factors
_CNC_BASE_COST: float = 25.0  # USD minimum setup
_CNC_COMPLEXITY_PER_CM3: float = 0.80  # USD per cm3 of bounding volume

# Sheet metal cost factors
_SHEET_METAL_PER_CM2: float = 0.02  # USD per cm2 of flat area
_SHEET_BENDING_FACTOR: float = 1.5  # multiplier per bend operation

# Default material cost when none is available
_DEFAULT_COST_PER_KG: float = 30.0  # generic engineering plastic/aluminum


# ---------------------------------------------------------------------------
# Estimation functions
# ---------------------------------------------------------------------------

def _material_cost_from_spec(spec: ComponentSpec) -> float:
    """Compute raw material cost from spec volume and material density/cost.

    Returns 0.0 if insufficient data is available.
    """
    if spec.material is None:
        return 0.0

    cost_per_kg = spec.material.cost_per_kg
    if cost_per_kg is None or cost_per_kg <= 0.0:
        cost_per_kg = _DEFAULT_COST_PER_KG

    density = spec.material.density_g_cm3

    # Estimate volume from mass if dimensions aren't directly available.
    volume_cm3 = 0.0
    dims = spec.dimensions
    if dims:
        # Try to compute bounding volume (rough proxy)
        length = float(dims.get("length_mm", dims.get("length", 0))) / 10.0
        width = float(dims.get("width_mm", dims.get("width", 0))) / 10.0
        height = float(dims.get("height_mm", dims.get("height", 0))) / 10.0
        if length > 0 and width > 0 and height > 0:
            volume_cm3 = length * width * height

    if volume_cm3 <= 0.0 and spec.mass_g is not None and density > 0:
        volume_cm3 = spec.mass_g / density

    if volume_cm3 <= 0.0:
        return 0.0

    mass_kg = volume_cm3 * density / 1000.0
    return mass_kg * cost_per_kg


def _estimate_fdm(spec: ComponentSpec) -> CostEstimate:
    """Estimate cost for FDM 3D printing."""
    mat_cost = _material_cost_from_spec(spec) * _FDM_MARKUP

    volume_cm3 = _volume_from_spec(spec)
    mfg_cost = volume_cm3 * _FDM_MACHINE_RATE_PER_CM3

    total = mat_cost + mfg_cost
    return CostEstimate(
        material_cost=round(mat_cost, 2),
        manufacturing_cost=round(mfg_cost, 2),
        total_cost=round(total, 2),
        method="FDM 3D Print",
        notes=f"Volume ~{volume_cm3:.1f} cm3, {_FDM_MARKUP}x material markup",
    )


def _estimate_sla(spec: ComponentSpec) -> CostEstimate:
    """Estimate cost for SLA resin printing."""
    mat_cost = _material_cost_from_spec(spec) * _SLA_MARKUP
    volume_cm3 = _volume_from_spec(spec)
    mfg_cost = volume_cm3 * _SLA_MACHINE_RATE_PER_CM3
    total = mat_cost + mfg_cost
    return CostEstimate(
        material_cost=round(mat_cost, 2),
        manufacturing_cost=round(mfg_cost, 2),
        total_cost=round(total, 2),
        method="SLA Resin Print",
        notes=f"Volume ~{volume_cm3:.1f} cm3, {_SLA_MARKUP}x material markup",
    )


def _estimate_sls(spec: ComponentSpec) -> CostEstimate:
    """Estimate cost for SLS powder printing."""
    mat_cost = _material_cost_from_spec(spec) * _SLS_MARKUP
    volume_cm3 = _volume_from_spec(spec)
    mfg_cost = volume_cm3 * _SLS_MACHINE_RATE_PER_CM3
    total = mat_cost + mfg_cost
    return CostEstimate(
        material_cost=round(mat_cost, 2),
        manufacturing_cost=round(mfg_cost, 2),
        total_cost=round(total, 2),
        method="SLS Powder Print",
        notes=f"Volume ~{volume_cm3:.1f} cm3, {_SLS_MARKUP}x material markup",
    )


def _estimate_cnc(spec: ComponentSpec) -> CostEstimate:
    """Estimate cost for CNC machining."""
    mat_cost = _material_cost_from_spec(spec)
    volume_cm3 = _volume_from_spec(spec)
    mfg_cost = _CNC_BASE_COST + _CNC_COMPLEXITY_PER_CM3 * volume_cm3
    total = mat_cost + mfg_cost
    return CostEstimate(
        material_cost=round(mat_cost, 2),
        manufacturing_cost=round(mfg_cost, 2),
        total_cost=round(total, 2),
        method="CNC Machining",
        notes=(
            f"Base ${_CNC_BASE_COST:.0f} + "
            f"${_CNC_COMPLEXITY_PER_CM3:.2f}/cm3 x {volume_cm3:.1f} cm3"
        ),
    )


def _estimate_sheet_metal(spec: ComponentSpec) -> CostEstimate:
    """Estimate cost for sheet metal fabrication."""
    mat_cost = _material_cost_from_spec(spec)

    dims = spec.dimensions
    length_cm = float(dims.get("length_mm", dims.get("length", 100))) / 10.0
    width_cm = float(dims.get("width_mm", dims.get("width", 100))) / 10.0
    thickness_mm = float(dims.get("thickness_mm", dims.get("thickness", 1)))

    area_cm2 = length_cm * width_cm
    mfg_cost = area_cm2 * _SHEET_METAL_PER_CM2 * (thickness_mm / 1.0)
    mfg_cost *= _SHEET_BENDING_FACTOR
    total = mat_cost + mfg_cost
    return CostEstimate(
        material_cost=round(mat_cost, 2),
        manufacturing_cost=round(mfg_cost, 2),
        total_cost=round(total, 2),
        method="Sheet Metal",
        notes=f"Area ~{area_cm2:.1f} cm2, thickness {thickness_mm} mm",
    )


def _estimate_cots(spec: ComponentSpec) -> CostEstimate:
    """Return the procurement cost for a COTS part."""
    unit_cost = 0.0
    supplier = ""
    if spec.procurement:
        raw_cost = spec.procurement.get("unit_cost")
        if raw_cost is not None:
            unit_cost = float(raw_cost)
        supplier = str(spec.procurement.get("supplier", ""))

    return CostEstimate(
        material_cost=0.0,
        manufacturing_cost=0.0,
        total_cost=round(unit_cost, 2),
        method="COTS Procurement",
        notes=f"Purchased from {supplier}" if supplier else "Purchased (no supplier listed)",
    )


def _volume_from_spec(spec: ComponentSpec) -> float:
    """Estimate volume in cm3 from spec dimensions or mass/density."""
    dims = spec.dimensions
    if dims:
        length = float(dims.get("length_mm", dims.get("length", 0))) / 10.0
        width = float(dims.get("width_mm", dims.get("width", 0))) / 10.0
        height = float(dims.get("height_mm", dims.get("height", 0))) / 10.0
        if length > 0 and width > 0 and height > 0:
            return length * width * height

    if spec.mass_g is not None and spec.material is not None:
        density = spec.material.density_g_cm3
        if density > 0:
            return spec.mass_g / density

    return 0.0


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_METHOD_ESTIMATORS: dict[str, type] = {}  # unused, see below

_ESTIMATOR_MAP = {
    "fdm": _estimate_fdm,
    "sla": _estimate_sla,
    "sls": _estimate_sls,
    "cnc": _estimate_cnc,
    "sheet_metal": _estimate_sheet_metal,
    "cots": _estimate_cots,
}


def estimate_manufacturing_cost(spec: ComponentSpec) -> CostEstimate:
    """Estimate the manufacturing cost for a component.

    Dispatches to a method-specific estimator based on the component's
    ``metadata["manufacturing_method"]`` value.  If the component is COTS,
    the procurement unit cost is returned directly.  For unknown methods,
    a zero-cost estimate is returned with a descriptive note.

    Args:
        spec: The component specification to estimate.

    Returns:
        A ``CostEstimate`` with material, manufacturing, and total costs.
    """
    # COTS parts always use procurement pricing.
    if spec.is_cots:
        return _estimate_cots(spec)

    method_key = str(spec.metadata.get("manufacturing_method", "")).lower()
    estimator = _ESTIMATOR_MAP.get(method_key)

    if estimator is not None:
        return estimator(spec)

    # Unknown or unspecified method -- return zero with a note.
    return CostEstimate(
        material_cost=0.0,
        manufacturing_cost=0.0,
        total_cost=0.0,
        method=method_key or "unknown",
        notes="No cost heuristic available for this manufacturing method.",
    )
