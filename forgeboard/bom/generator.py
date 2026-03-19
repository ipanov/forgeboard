"""Bill of materials generation from a solved assembly.

Walks every solved part in a ``SolvedAssembly``, resolves its full
specification via the ``ComponentRegistry``, and produces a structured
``BillOfMaterials`` with aggregated totals for mass, cost, and part
classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forgeboard.assembly.orchestrator import SolvedAssembly
from forgeboard.core.registry import ComponentRegistry
from forgeboard.core.types import BOMEntry, ComponentSpec


# ---------------------------------------------------------------------------
# BillOfMaterials
# ---------------------------------------------------------------------------

@dataclass
class BillOfMaterials:
    """Aggregated bill of materials for an assembly.

    Attributes:
        entries: Ordered list of BOM line items.
        total_mass_g: Sum of all entry masses (quantity-weighted).
        total_cost: Sum of all entry total_cost values.
        currency: ISO currency code for monetary values.
        cots_count: Number of off-the-shelf (COTS) entries.
        custom_count: Number of custom-manufactured entries.
        fastener_count: Number of fastener entries.
    """

    entries: list[BOMEntry] = field(default_factory=list)
    total_mass_g: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"
    cots_count: int = 0
    custom_count: int = 0
    fastener_count: int = 0

    def summary(self) -> str:
        """Return a human-readable text summary of the BOM."""
        lines: list[str] = [
            f"Bill of Materials -- {len(self.entries)} line items",
            f"{'=' * 50}",
        ]

        # Header row.
        header = (
            f"{'Part Name':<30s} {'Qty':>4s} {'Mass(g)':>8s} "
            f"{'Unit($)':>8s} {'Total($)':>9s}"
        )
        lines.append(header)
        lines.append("-" * len(header))

        for entry in self.entries:
            mass_str = f"{entry.mass_g:.1f}" if entry.mass_g is not None else "N/A"
            unit_str = f"{entry.unit_cost:.2f}" if entry.unit_cost is not None else "N/A"
            total_str = (
                f"{entry.total_cost:.2f}" if entry.total_cost is not None else "N/A"
            )
            lines.append(
                f"{entry.part_name:<30s} {entry.quantity:>4d} "
                f"{mass_str:>8s} {unit_str:>8s} "
                f"{total_str:>9s}"
            )

        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL':<30s} {'':>4s} "
            f"{self.total_mass_g:>8.1f} {'':>8s} "
            f"{self.total_cost:>9.2f} {self.currency}"
        )
        lines.append("")
        lines.append(f"COTS parts:   {self.cots_count}")
        lines.append(f"Custom parts: {self.custom_count}")
        lines.append(f"Fasteners:    {self.fastener_count}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _spec_to_entry(spec: ComponentSpec, quantity: int = 1) -> BOMEntry:
    """Convert a ComponentSpec into a BOMEntry line item.

    Args:
        spec: The component specification to convert.
        quantity: Override quantity (defaults to 1 per solved-part instance).
    """
    material_name = spec.material.name if spec.material else ""
    supplier = ""
    unit_cost: float | None = None

    # Extract supplier and unit cost from procurement dict.
    if spec.procurement:
        supplier = str(spec.procurement.get("supplier", ""))
        raw_cost = spec.procurement.get("unit_cost") or spec.procurement.get("unit_cost_usd")
        if raw_cost is not None:
            unit_cost = float(raw_cost)

    total_cost: float | None = None
    if unit_cost is not None:
        total_cost = round(unit_cost * quantity, 2)

    # Determine manufacturing method from metadata or default to empty.
    manufacturing_method = str(spec.metadata.get("manufacturing_method", ""))

    # Detect fastener status from metadata.
    is_fastener = bool(spec.metadata.get("is_fastener", False))

    return BOMEntry(
        part_name=spec.name,
        part_id=spec.id,
        quantity=quantity,
        material=material_name,
        mass_g=spec.mass_g,
        unit_cost=unit_cost,
        total_cost=total_cost,
        supplier=supplier,
        is_cots=spec.is_cots,
        manufacturing_method=manufacturing_method,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_bom(
    assembly: SolvedAssembly,
    registry: ComponentRegistry,
) -> BillOfMaterials:
    """Generate a bill of materials from a solved assembly.

    For each solved part, the function attempts to look up a richer
    ``ComponentSpec`` in the *registry* by matching the shape name against
    component IDs.  If no registry match is found, a minimal BOM entry is
    still created from the part name alone.

    Args:
        assembly: A fully solved assembly with positioned parts.
        registry: Component registry containing full specifications.

    Returns:
        A populated ``BillOfMaterials`` instance with aggregated totals.
    """
    entries: list[BOMEntry] = []
    total_mass = 0.0
    total_cost = 0.0
    cots = 0
    custom = 0
    fasteners = 0

    for part_name, solved_part in assembly.parts.items():
        # Try to look up a full spec from the registry.
        spec = registry.get(part_name)
        if spec is None:
            # Fallback: create a minimal spec from the part name.
            spec = ComponentSpec(name=part_name, id=part_name)

        entry = _spec_to_entry(spec)
        entries.append(entry)

        # Accumulate totals, treating None values as zero for aggregation.
        entry_mass = entry.mass_g if entry.mass_g is not None else 0.0
        entry_cost = entry.total_cost if entry.total_cost is not None else 0.0
        total_mass += entry_mass * entry.quantity
        total_cost += entry_cost

        if entry.is_cots and not bool(spec.metadata.get("is_fastener", False)):
            cots += entry.quantity
        elif bool(spec.metadata.get("is_fastener", False)):
            fasteners += entry.quantity
        else:
            custom += entry.quantity

    return BillOfMaterials(
        entries=entries,
        total_mass_g=total_mass,
        total_cost=total_cost,
        cots_count=cots,
        custom_count=custom,
        fastener_count=fasteners,
    )
