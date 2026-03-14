"""BOM export to CSV, JSON, and Markdown formats.

Each function takes a ``BillOfMaterials`` and writes it to a file in the
requested format, returning the resolved output path.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from forgeboard.bom.generator import BillOfMaterials

logger = logging.getLogger(__name__)

# CSV column order -- matches the spec requirement.
CSV_COLUMNS: list[str] = [
    "Part Name",
    "Part ID",
    "Qty",
    "Material",
    "Mass (g)",
    "Unit Cost",
    "Total Cost",
    "Supplier",
    "COTS?",
    "Manufacturing Method",
]


def export_csv(bom: BillOfMaterials, path: str) -> Path:
    """Export the BOM as a CSV file.

    Columns: Part Name, Part ID, Qty, Material, Mass (g), Unit Cost,
    Total Cost, Supplier, COTS?, Manufacturing Method.

    Args:
        bom: Populated bill of materials.
        path: Destination file path.

    Returns:
        Resolved ``Path`` of the written CSV file.
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)

        for entry in bom.entries:
            writer.writerow([
                entry.part_name,
                entry.part_id,
                entry.quantity,
                entry.material,
                f"{entry.mass_g:.1f}" if entry.mass_g is not None else "",
                f"{entry.unit_cost:.2f}" if entry.unit_cost is not None else "",
                f"{entry.total_cost:.2f}" if entry.total_cost is not None else "",
                entry.supplier,
                "Yes" if entry.is_cots else "No",
                entry.manufacturing_method,
            ])

    logger.info("BOM CSV export complete: %s (%d entries)", output, len(bom.entries))
    return output


def export_json(bom: BillOfMaterials, path: str) -> Path:
    """Export the BOM as a structured JSON file.

    The JSON document contains a ``metadata`` header with totals and
    classification counts, followed by an ``entries`` array with one object
    per BOM line item.

    Args:
        bom: Populated bill of materials.
        path: Destination file path.

    Returns:
        Resolved ``Path`` of the written JSON file.
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator": "ForgeBoard",
            "total_entries": len(bom.entries),
            "total_mass_g": round(bom.total_mass_g, 2),
            "total_cost": round(bom.total_cost, 2),
            "currency": bom.currency,
            "cots_count": bom.cots_count,
            "custom_count": bom.custom_count,
            "fastener_count": bom.fastener_count,
        },
        "entries": [
            {
                "part_name": e.part_name,
                "part_id": e.part_id,
                "quantity": e.quantity,
                "material": e.material,
                "mass_g": e.mass_g,
                "unit_cost": e.unit_cost,
                "total_cost": e.total_cost,
                "supplier": e.supplier,
                "is_cots": e.is_cots,
                "manufacturing_method": e.manufacturing_method,
            }
            for e in bom.entries
        ],
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    logger.info("BOM JSON export complete: %s (%d entries)", output, len(bom.entries))
    return output


def export_markdown(bom: BillOfMaterials, path: str) -> Path:
    """Export the BOM as a GitHub-flavored Markdown table.

    Args:
        bom: Populated bill of materials.
        path: Destination file path.

    Returns:
        Resolved ``Path`` of the written Markdown file.
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Bill of Materials",
        "",
        "| Part Name | Part ID | Qty | Material | Mass (g) "
        "| Unit Cost | Total Cost | Supplier | COTS? | Mfg Method |",
        "|-----------|---------|----:|----------|--------:"
        "|---------:|---------:|----------|-------|------------|",
    ]

    for e in bom.entries:
        mass_str = f"{e.mass_g:.1f}" if e.mass_g is not None else "-"
        unit_str = f"{e.unit_cost:.2f}" if e.unit_cost is not None else "-"
        total_str = f"{e.total_cost:.2f}" if e.total_cost is not None else "-"
        cots_str = "Yes" if e.is_cots else "No"
        lines.append(
            f"| {e.part_name} | {e.part_id} | {e.quantity} | {e.material} "
            f"| {mass_str} | {unit_str} | {total_str} "
            f"| {e.supplier} | {cots_str} | {e.manufacturing_method} |"
        )

    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total mass:** {bom.total_mass_g:.1f} g")
    lines.append(
        f"- **Total cost:** {bom.total_cost:.2f} {bom.currency}"
    )
    lines.append(f"- **COTS parts:** {bom.cots_count}")
    lines.append(f"- **Custom parts:** {bom.custom_count}")
    lines.append(f"- **Fasteners:** {bom.fastener_count}")
    lines.append("")

    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(
        "BOM Markdown export complete: %s (%d entries)",
        output,
        len(bom.entries),
    )
    return output
