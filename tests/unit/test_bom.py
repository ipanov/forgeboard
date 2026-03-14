"""Unit tests for BOM generation, export, and cost estimation.

Tests cover:
- BOM generation from a mock assembly with three parts
- CSV export format correctness
- JSON export structure
- Cost estimation for different manufacturing methods
- Total calculations (mass, cost)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from forgeboard.assembly.orchestrator import SolvedAssembly, SolvedPart
from forgeboard.bom.costing import CostEstimate, estimate_manufacturing_cost
from forgeboard.bom.export import export_csv, export_json, export_markdown
from forgeboard.bom.generator import BillOfMaterials, generate_bom
from forgeboard.core.registry import ComponentRegistry
from forgeboard.core.types import (
    BOMEntry,
    ComponentSpec,
    Material,
    Placement,
    Vector3,
)
from forgeboard.engines.base import Shape


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def aluminum() -> Material:
    """Aluminum 6061 material."""
    return Material(
        name="Aluminum_6061",
        density_g_cm3=2.7,
        yield_strength_mpa=276.0,
        cost_per_kg=8.0,
    )


@pytest.fixture
def pla() -> Material:
    """PLA 3D printing filament material."""
    return Material(
        name="PLA",
        density_g_cm3=1.24,
        cost_per_kg=25.0,
    )


@pytest.fixture
def bracket_spec(aluminum: Material) -> ComponentSpec:
    """Custom CNC-machined bracket."""
    return ComponentSpec(
        name="Mounting_Bracket",
        id="BRKT-001",
        description="L-shaped mounting bracket",
        material=aluminum,
        dimensions={"length_mm": 40, "width_mm": 30, "height_mm": 20},
        mass_g=65.0,
        is_cots=False,
        procurement={},
        metadata={"manufacturing_method": "cnc"},
    )


@pytest.fixture
def motor_spec() -> ComponentSpec:
    """COTS motor component."""
    return ComponentSpec(
        name="NEMA17_Motor",
        id="MOT-001",
        description="NEMA 17 stepper motor",
        mass_g=350.0,
        is_cots=True,
        procurement={
            "supplier": "StepperOnline",
            "unit_cost": 12.50,
            "part_number": "17HS4401",
        },
    )


@pytest.fixture
def bolt_spec() -> ComponentSpec:
    """Fastener component."""
    return ComponentSpec(
        name="M5_Bolt",
        id="FST-001",
        description="M5x20 hex bolt",
        mass_g=5.0,
        is_cots=True,
        procurement={
            "supplier": "McMaster",
            "unit_cost": 0.15,
        },
        metadata={"is_fastener": True},
    )


@pytest.fixture
def registry(
    bracket_spec: ComponentSpec,
    motor_spec: ComponentSpec,
    bolt_spec: ComponentSpec,
) -> ComponentRegistry:
    """Registry pre-loaded with three test specs."""
    reg = ComponentRegistry()
    reg.add(bracket_spec)
    reg.add(motor_spec)
    reg.add(bolt_spec)
    return reg


@pytest.fixture
def mock_assembly() -> SolvedAssembly:
    """Solved assembly with three parts."""
    identity = Placement.identity()
    dummy_shape = Shape(native=None, name="dummy")

    return SolvedAssembly(
        name="TestAssembly",
        parts={
            "BRKT-001": SolvedPart(
                name="BRKT-001",
                shape=dummy_shape,
                placement=identity,
            ),
            "MOT-001": SolvedPart(
                name="MOT-001",
                shape=dummy_shape,
                placement=identity,
            ),
            "FST-001": SolvedPart(
                name="FST-001",
                shape=dummy_shape,
                placement=identity,
            ),
        },
    )


# ---------------------------------------------------------------------------
# BOM generation tests
# ---------------------------------------------------------------------------

class TestGenerateBom:
    """Tests for generate_bom()."""

    def test_generates_correct_number_of_entries(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        assert len(bom.entries) == 3

    def test_total_mass_is_sum_of_part_masses(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        # bracket=65, motor=350, bolt=5 => 420
        assert bom.total_mass_g == pytest.approx(420.0)

    def test_total_cost_sums_procurement_costs(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        # motor=$12.50, bolt=$0.15, bracket=no procurement => $12.65
        assert bom.total_cost == pytest.approx(12.65)

    def test_cots_count(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        # motor is COTS but not fastener
        assert bom.cots_count == 1

    def test_fastener_count(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        # bolt has is_fastener=True in metadata
        assert bom.fastener_count == 1

    def test_custom_count(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        # bracket is custom (not COTS, not fastener)
        assert bom.custom_count == 1

    def test_entry_part_id_matches_spec(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        ids = {e.part_id for e in bom.entries}
        assert "BRKT-001" in ids
        assert "MOT-001" in ids
        assert "FST-001" in ids

    def test_summary_includes_totals(
        self, mock_assembly: SolvedAssembly, registry: ComponentRegistry
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        text = bom.summary()
        assert "TOTAL" in text
        assert "3 line items" in text
        assert "COTS parts:" in text

    def test_empty_assembly_produces_empty_bom(
        self, registry: ComponentRegistry
    ) -> None:
        empty = SolvedAssembly(name="Empty")
        bom = generate_bom(empty, registry)
        assert len(bom.entries) == 0
        assert bom.total_mass_g == 0.0
        assert bom.total_cost == 0.0


# ---------------------------------------------------------------------------
# CSV export tests
# ---------------------------------------------------------------------------

class TestExportCsv:
    """Tests for export_csv()."""

    def test_csv_has_correct_header(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        csv_path = export_csv(bom, str(tmp_path / "bom.csv"))

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)

        assert header[0] == "Part Name"
        assert header[1] == "Part ID"
        assert "Qty" in header
        assert "COTS?" in header

    def test_csv_has_correct_row_count(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        csv_path = export_csv(bom, str(tmp_path / "bom.csv"))

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        # 1 header + 3 data rows
        assert len(rows) == 4

    def test_csv_cots_column(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        csv_path = export_csv(bom, str(tmp_path / "bom.csv"))

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        motor_row = [r for r in rows if r["Part Name"] == "NEMA17_Motor"][0]
        assert motor_row["COTS?"] == "Yes"

        bracket_row = [r for r in rows if r["Part Name"] == "Mounting_Bracket"][0]
        assert bracket_row["COTS?"] == "No"


# ---------------------------------------------------------------------------
# JSON export tests
# ---------------------------------------------------------------------------

class TestExportJson:
    """Tests for export_json()."""

    def test_json_has_metadata_and_entries(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        json_path = export_json(bom, str(tmp_path / "bom.json"))

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "metadata" in data
        assert "entries" in data
        assert len(data["entries"]) == 3

    def test_json_metadata_totals(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        json_path = export_json(bom, str(tmp_path / "bom.json"))

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        meta = data["metadata"]
        assert meta["total_mass_g"] == pytest.approx(420.0)
        assert meta["total_entries"] == 3
        assert meta["currency"] == "USD"

    def test_json_entry_structure(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        json_path = export_json(bom, str(tmp_path / "bom.json"))

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        entry = data["entries"][0]
        expected_keys = {
            "part_name", "part_id", "quantity", "material",
            "mass_g", "unit_cost", "total_cost", "supplier",
            "is_cots", "manufacturing_method",
        }
        assert expected_keys <= set(entry.keys())


# ---------------------------------------------------------------------------
# Cost estimation tests
# ---------------------------------------------------------------------------

class TestCostEstimation:
    """Tests for estimate_manufacturing_cost()."""

    def test_cots_returns_procurement_cost(self, motor_spec: ComponentSpec) -> None:
        est = estimate_manufacturing_cost(motor_spec)
        assert est.total_cost == pytest.approx(12.50)
        assert est.method == "COTS Procurement"
        assert est.material_cost == 0.0

    def test_cnc_includes_base_cost(self, bracket_spec: ComponentSpec) -> None:
        est = estimate_manufacturing_cost(bracket_spec)
        assert est.method == "CNC Machining"
        # CNC should have base cost of $25 + volume component
        assert est.manufacturing_cost >= 25.0
        assert est.total_cost > 0.0

    def test_fdm_uses_volume_estimate(self, pla: Material) -> None:
        spec = ComponentSpec(
            name="Test_Part",
            id="TEST-001",
            material=pla,
            dimensions={"length_mm": 50, "width_mm": 30, "height_mm": 20},
            mass_g=37.2,
            metadata={"manufacturing_method": "fdm"},
        )
        est = estimate_manufacturing_cost(spec)
        assert est.method == "FDM 3D Print"
        assert est.material_cost > 0.0
        assert est.manufacturing_cost > 0.0

    def test_unknown_method_returns_zero(self) -> None:
        spec = ComponentSpec(
            name="Unknown_Part",
            id="UNK-001",
            metadata={"manufacturing_method": "teleportation"},
        )
        est = estimate_manufacturing_cost(spec)
        assert est.total_cost == 0.0
        assert "No cost heuristic" in est.notes

    def test_sheet_metal_estimate(self, aluminum: Material) -> None:
        spec = ComponentSpec(
            name="Panel",
            id="PNL-001",
            material=aluminum,
            dimensions={"length_mm": 200, "width_mm": 100, "thickness_mm": 2},
            mass_g=108.0,
            metadata={"manufacturing_method": "sheet_metal"},
        )
        est = estimate_manufacturing_cost(spec)
        assert est.method == "Sheet Metal"
        assert est.total_cost > 0.0


# ---------------------------------------------------------------------------
# Markdown export tests
# ---------------------------------------------------------------------------

class TestExportMarkdown:
    """Tests for export_markdown()."""

    def test_markdown_contains_table_header(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        md_path = export_markdown(bom, str(tmp_path / "bom.md"))
        content = md_path.read_text(encoding="utf-8")
        assert "| Part Name |" in content
        assert "## Summary" in content

    def test_markdown_contains_all_parts(
        self,
        mock_assembly: SolvedAssembly,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        bom = generate_bom(mock_assembly, registry)
        md_path = export_markdown(bom, str(tmp_path / "bom.md"))
        content = md_path.read_text(encoding="utf-8")
        assert "Mounting_Bracket" in content
        assert "NEMA17_Motor" in content
        assert "M5_Bolt" in content
