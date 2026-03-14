"""Unit tests for ForgeBoard core types.

Tests cover:
- Vector3 creation and validation
- BoundingBox overlap detection
- ComponentSpec serialization/deserialization (YAML round-trip)
- InterfacePoint normal vector validation
- Material with realistic values
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from forgeboard.core.types import (
    AXIS_X,
    AXIS_Y,
    AXIS_Z,
    ORIGIN,
    BOMEntry,
    BoundingBox,
    ComponentSpec,
    InterfacePoint,
    InterfaceType,
    Material,
    Placement,
    Vector3,
)


# ---------------------------------------------------------------------------
# Vector3 tests
# ---------------------------------------------------------------------------

class TestVector3:
    """Tests for Vector3 creation, arithmetic, and methods."""

    def test_default_is_origin(self) -> None:
        v = Vector3()
        assert v.x == 0.0
        assert v.y == 0.0
        assert v.z == 0.0

    def test_keyword_construction(self) -> None:
        v = Vector3(x=1.0, y=2.0, z=3.0)
        assert v.x == 1.0
        assert v.y == 2.0
        assert v.z == 3.0

    def test_addition(self) -> None:
        a = Vector3(x=1.0, y=2.0, z=3.0)
        b = Vector3(x=4.0, y=5.0, z=6.0)
        result = a + b
        assert result.x == pytest.approx(5.0)
        assert result.y == pytest.approx(7.0)
        assert result.z == pytest.approx(9.0)

    def test_subtraction(self) -> None:
        a = Vector3(x=5.0, y=7.0, z=9.0)
        b = Vector3(x=1.0, y=2.0, z=3.0)
        result = a - b
        assert result.x == pytest.approx(4.0)
        assert result.y == pytest.approx(5.0)
        assert result.z == pytest.approx(6.0)

    def test_scalar_multiply(self) -> None:
        v = Vector3(x=1.0, y=2.0, z=3.0)
        result = v * 2.0
        assert result.x == pytest.approx(2.0)
        assert result.y == pytest.approx(4.0)
        assert result.z == pytest.approx(6.0)

    def test_scalar_rmul(self) -> None:
        v = Vector3(x=1.0, y=2.0, z=3.0)
        result = 3.0 * v
        assert result.x == pytest.approx(3.0)
        assert result.y == pytest.approx(6.0)
        assert result.z == pytest.approx(9.0)

    def test_negation(self) -> None:
        v = Vector3(x=1.0, y=-2.0, z=3.0)
        result = -v
        assert result.x == pytest.approx(-1.0)
        assert result.y == pytest.approx(2.0)
        assert result.z == pytest.approx(-3.0)

    def test_dot_product(self) -> None:
        a = Vector3(x=1.0, y=0.0, z=0.0)
        b = Vector3(x=0.0, y=1.0, z=0.0)
        assert a.dot(b) == pytest.approx(0.0)

        c = Vector3(x=1.0, y=2.0, z=3.0)
        d = Vector3(x=4.0, y=5.0, z=6.0)
        assert c.dot(d) == pytest.approx(32.0)

    def test_cross_product(self) -> None:
        result = AXIS_X.cross(AXIS_Y)
        assert result.x == pytest.approx(0.0)
        assert result.y == pytest.approx(0.0)
        assert result.z == pytest.approx(1.0)

    def test_length(self) -> None:
        v = Vector3(x=3.0, y=4.0, z=0.0)
        assert v.length() == pytest.approx(5.0)

    def test_normalized_unit_length(self) -> None:
        v = Vector3(x=3.0, y=4.0, z=0.0)
        n = v.normalized()
        assert n.length() == pytest.approx(1.0)
        assert n.x == pytest.approx(0.6)
        assert n.y == pytest.approx(0.8)

    def test_normalized_zero_vector(self) -> None:
        v = Vector3(x=0.0, y=0.0, z=0.0)
        n = v.normalized()
        assert n.length() == pytest.approx(0.0)

    def test_as_tuple(self) -> None:
        v = Vector3(x=1.0, y=2.0, z=3.0)
        assert v.as_tuple() == (1.0, 2.0, 3.0)

    def test_frozen_immutability(self) -> None:
        v = Vector3(x=1.0, y=2.0, z=3.0)
        with pytest.raises(Exception):
            v.x = 10.0  # type: ignore[misc]

    def test_axis_constants(self) -> None:
        assert AXIS_X.x == 1.0 and AXIS_X.y == 0.0 and AXIS_X.z == 0.0
        assert AXIS_Y.x == 0.0 and AXIS_Y.y == 1.0 and AXIS_Y.z == 0.0
        assert AXIS_Z.x == 0.0 and AXIS_Z.y == 0.0 and AXIS_Z.z == 1.0
        assert ORIGIN.x == 0.0 and ORIGIN.y == 0.0 and ORIGIN.z == 0.0


# ---------------------------------------------------------------------------
# BoundingBox tests
# ---------------------------------------------------------------------------

class TestBoundingBox:
    """Tests for BoundingBox overlap detection and properties."""

    def test_scalar_constructor(self) -> None:
        bb = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=20, z_max=30)
        assert bb.x_min == 0.0
        assert bb.y_max == 20.0
        assert bb.size_x == pytest.approx(10.0)
        assert bb.size_y == pytest.approx(20.0)
        assert bb.size_z == pytest.approx(30.0)

    def test_vector_constructor(self) -> None:
        bb = BoundingBox(
            min_corner=Vector3(x=1.0, y=2.0, z=3.0),
            max_corner=Vector3(x=4.0, y=5.0, z=6.0),
        )
        assert bb.x_min == pytest.approx(1.0)
        assert bb.z_max == pytest.approx(6.0)

    def test_volume(self) -> None:
        bb = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=20, z_max=30)
        assert bb.volume == pytest.approx(6000.0)

    def test_center(self) -> None:
        bb = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=20, z_max=30)
        c = bb.center
        assert c.x == pytest.approx(5.0)
        assert c.y == pytest.approx(10.0)
        assert c.z == pytest.approx(15.0)

    def test_overlapping_boxes(self) -> None:
        a = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=10, z_max=10)
        b = BoundingBox(x_min=5, y_min=5, z_min=5, x_max=15, y_max=15, z_max=15)
        assert a.overlaps(b) is True
        assert b.overlaps(a) is True

    def test_non_overlapping_boxes(self) -> None:
        a = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=10, z_max=10)
        b = BoundingBox(x_min=20, y_min=20, z_min=20, x_max=30, y_max=30, z_max=30)
        assert a.overlaps(b) is False

    def test_touching_boxes_overlap(self) -> None:
        a = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=10, z_max=10)
        b = BoundingBox(x_min=10, y_min=0, z_min=0, x_max=20, y_max=10, z_max=10)
        # Touching at boundary -- overlaps returns True (shared face counts)
        assert a.overlaps(b) is True

    def test_overlap_with_margin(self) -> None:
        a = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=10, z_max=10)
        b = BoundingBox(x_min=11, y_min=0, z_min=0, x_max=20, y_max=10, z_max=10)
        # 1mm gap, but with 2mm margin they should overlap
        assert a.overlaps(b, margin=2.0) is True
        assert a.overlaps(b, margin=0.0) is False

    def test_expanded(self) -> None:
        bb = BoundingBox(x_min=0, y_min=0, z_min=0, x_max=10, y_max=10, z_max=10)
        expanded = bb.expanded(5.0)
        assert expanded.x_min == pytest.approx(-5.0)
        assert expanded.x_max == pytest.approx(15.0)

    def test_invalid_corners_raise(self) -> None:
        with pytest.raises(ValueError):
            BoundingBox(x_min=10, y_min=0, z_min=0, x_max=0, y_max=10, z_max=10)


# ---------------------------------------------------------------------------
# ComponentSpec tests
# ---------------------------------------------------------------------------

class TestComponentSpec:
    """Tests for ComponentSpec serialization and validation."""

    def test_basic_creation(self) -> None:
        spec = ComponentSpec(
            name="Bracket",
            id="BRKT-001",
            description="Test bracket",
            mass_g=100.0,
        )
        assert spec.name == "Bracket"
        assert spec.id == "BRKT-001"
        assert spec.mass_g == pytest.approx(100.0)

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id must not be empty"):
            ComponentSpec(name="Test", id="  ")

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name must not be empty"):
            ComponentSpec(name="  ", id="TEST-001")

    def test_yaml_round_trip(self, tmp_path: Path) -> None:
        """ComponentSpec should survive YAML serialization and deserialization."""
        original = ComponentSpec(
            name="Test_Part",
            id="TP-001",
            description="A test component",
            category="structure",
            material=Material(
                name="Steel",
                density_g_cm3=7.85,
                yield_strength_mpa=250.0,
                cost_per_kg=5.0,
            ),
            dimensions={"length_mm": 100, "width_mm": 50, "height_mm": 25},
            mass_g=981.25,
            is_cots=False,
        )

        yaml_path = tmp_path / "spec.yaml"

        # Serialize to YAML
        data = original.model_dump()
        yaml_path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

        # Deserialize back
        loaded_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        restored = ComponentSpec(**loaded_data)

        assert restored.name == original.name
        assert restored.id == original.id
        assert restored.mass_g == pytest.approx(original.mass_g)  # type: ignore[arg-type]
        assert restored.material is not None
        assert restored.material.name == "Steel"
        assert restored.material.density_g_cm3 == pytest.approx(7.85)
        assert restored.dimensions["length_mm"] == 100

    def test_cots_spec(self) -> None:
        spec = ComponentSpec(
            name="Sensor",
            id="SNS-001",
            is_cots=True,
            procurement={"supplier": "Digi-Key", "unit_cost": 45.00},
        )
        assert spec.is_cots is True
        assert spec.procurement["unit_cost"] == 45.00


# ---------------------------------------------------------------------------
# InterfacePoint tests
# ---------------------------------------------------------------------------

class TestInterfacePoint:
    """Tests for InterfacePoint creation and normal validation."""

    def test_default_normal_is_z_up(self) -> None:
        ip = InterfacePoint(name="top")
        assert ip.normal.z == pytest.approx(1.0)
        assert ip.normal.x == pytest.approx(0.0)
        assert ip.normal.y == pytest.approx(0.0)

    def test_custom_normal(self) -> None:
        ip = InterfacePoint(
            name="side",
            position=Vector3(x=10.0, y=0.0, z=0.0),
            normal=Vector3(x=1.0, y=0.0, z=0.0),
        )
        assert ip.normal.x == pytest.approx(1.0)
        assert ip.position.x == pytest.approx(10.0)

    def test_flipped_reverses_normal(self) -> None:
        ip = InterfacePoint(
            name="face",
            normal=Vector3(x=0.0, y=0.0, z=1.0),
        )
        flipped = ip.flipped()
        assert flipped.normal.z == pytest.approx(-1.0)
        assert flipped.name == "face"

    def test_cylindrical_interface(self) -> None:
        ip = InterfacePoint(
            name="bore",
            type=InterfaceType.CYLINDRICAL,
            diameter_mm=10.0,
        )
        assert ip.type == InterfaceType.CYLINDRICAL
        assert ip.diameter_mm == pytest.approx(10.0)

    def test_negative_diameter_raises(self) -> None:
        with pytest.raises(ValueError):
            InterfacePoint(name="bad", diameter_mm=-5.0)


# ---------------------------------------------------------------------------
# Material tests
# ---------------------------------------------------------------------------

class TestMaterial:
    """Tests for Material with realistic engineering values."""

    def test_aluminum_6061(self) -> None:
        mat = Material(
            name="Aluminum_6061",
            density_g_cm3=2.7,
            yield_strength_mpa=276.0,
            cost_per_kg=8.0,
            manufacturing_methods=["CNC milling", "extrusion"],
        )
        assert mat.name == "Aluminum_6061"
        assert mat.density_g_cm3 == pytest.approx(2.7)
        assert mat.yield_strength_mpa == pytest.approx(276.0)
        assert mat.cost_per_kg == pytest.approx(8.0)
        assert "CNC milling" in mat.manufacturing_methods

    def test_pla_filament(self) -> None:
        mat = Material(
            name="PLA",
            density_g_cm3=1.24,
            cost_per_kg=25.0,
        )
        assert mat.density_g_cm3 == pytest.approx(1.24)
        assert mat.yield_strength_mpa is None

    def test_zero_density_raises(self) -> None:
        with pytest.raises(ValueError):
            Material(name="Invalid", density_g_cm3=0.0)

    def test_negative_density_raises(self) -> None:
        with pytest.raises(ValueError):
            Material(name="Invalid", density_g_cm3=-1.0)

    def test_frozen_immutability(self) -> None:
        mat = Material(name="Steel", density_g_cm3=7.85)
        with pytest.raises(Exception):
            mat.name = "Changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BOMEntry tests
# ---------------------------------------------------------------------------

class TestBOMEntry:
    """Tests for BOMEntry auto-calculation and immutability."""

    def test_auto_total_cost(self) -> None:
        entry = BOMEntry(
            part_name="Widget",
            part_id="WDG-001",
            quantity=3,
            unit_cost=10.0,
        )
        assert entry.total_cost == pytest.approx(30.0)

    def test_explicit_total_cost_preserved(self) -> None:
        entry = BOMEntry(
            part_name="Widget",
            part_id="WDG-001",
            quantity=3,
            unit_cost=10.0,
            total_cost=25.0,
        )
        assert entry.total_cost == pytest.approx(25.0)

    def test_frozen_entry(self) -> None:
        entry = BOMEntry(part_name="Test", part_id="T-001")
        with pytest.raises(Exception):
            entry.part_name = "Changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Placement tests
# ---------------------------------------------------------------------------

class TestPlacement:
    """Tests for Placement identity and construction."""

    def test_identity_placement(self) -> None:
        p = Placement.identity()
        assert p.position.x == pytest.approx(0.0)
        assert p.position.y == pytest.approx(0.0)
        assert p.position.z == pytest.approx(0.0)
        assert p.rotation_angle_deg == pytest.approx(0.0)

    def test_custom_placement(self) -> None:
        p = Placement(
            position=Vector3(x=10.0, y=20.0, z=30.0),
            rotation_axis=AXIS_Z,
            rotation_angle_deg=45.0,
        )
        assert p.position.x == pytest.approx(10.0)
        assert p.rotation_angle_deg == pytest.approx(45.0)
