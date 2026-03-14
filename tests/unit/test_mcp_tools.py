"""Tests for MCP tool functions.

Tests the tool functions directly (not via MCP protocol transport).
Each test calls the tool function and verifies the returned dict structure.
"""

from __future__ import annotations

import pytest

from forgeboard.mcp_server.server import get_project, reset_project, set_project


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_project():
    """Reset global project state before and after each test."""
    reset_project()
    yield
    reset_project()


# ---------------------------------------------------------------------------
# Import tools (registers them with FastMCP)
# ---------------------------------------------------------------------------

from forgeboard.mcp_server.tools import (
    forgeboard_add_component,
    forgeboard_add_dependency,
    forgeboard_add_to_assembly,
    forgeboard_analyze_text,
    forgeboard_buy_or_build,
    forgeboard_create_assembly,
    forgeboard_create_project,
    forgeboard_generate_bom,
    forgeboard_get_component,
    forgeboard_get_project_summary,
    forgeboard_list_components,
    forgeboard_preview_change,
    forgeboard_remove_component,
    forgeboard_search_cots,
    forgeboard_update_component,
    forgeboard_validate_assembly,
)


# ===========================================================================
# PROJECT MANAGEMENT
# ===========================================================================


class TestCreateProject:
    def test_create_returns_summary(self):
        result = forgeboard_create_project(name="Test Project")
        assert "error" not in result
        assert result["name"] == "Test Project"
        assert result["status"] == "created"
        assert result["component_count"] == 0
        assert result["assembly_count"] == 0

    def test_create_sets_global_project(self):
        forgeboard_create_project(name="Global Test")
        project = get_project()
        assert project.name == "Global Test"

    def test_create_with_invalid_registry_returns_error(self):
        result = forgeboard_create_project(
            name="Bad",
            registry_path="/nonexistent/registry.yaml",
        )
        assert "error" in result


class TestGetProjectSummary:
    def test_no_project_returns_error(self):
        result = forgeboard_get_project_summary()
        assert "error" in result

    def test_returns_summary_after_create(self):
        forgeboard_create_project(name="Summary Test")
        result = forgeboard_get_project_summary()
        assert "error" not in result
        assert result["name"] == "Summary Test"
        assert isinstance(result["components"], list)
        assert isinstance(result["assemblies"], list)


# ===========================================================================
# COMPONENT MANAGEMENT
# ===========================================================================


class TestAddComponent:
    def test_add_creates_component(self):
        forgeboard_create_project(name="Comp Test")
        result = forgeboard_add_component(
            name="Base Plate",
            id="PLATE-001",
            description="Aluminum base plate",
            dimensions={"length_mm": 100, "width_mm": 80, "thickness_mm": 3},
            material="Aluminum_6061",
            mass_g=65.0,
            is_cots=False,
        )
        assert "error" not in result
        assert result["name"] == "Base Plate"
        assert result["id"] == "PLATE-001"
        assert result["is_cots"] is False
        assert result["mass_g"] == 65.0

    def test_add_with_interfaces(self):
        forgeboard_create_project(name="Interface Test")
        result = forgeboard_add_component(
            name="Bracket",
            id="BRKT-001",
            interfaces={
                "top": {"name": "top", "diameter_mm": 5.0},
                "bottom": {"name": "bottom"},
            },
        )
        assert "error" not in result
        assert "top" in result["interfaces"]
        assert "bottom" in result["interfaces"]

    def test_add_without_project_returns_error(self):
        result = forgeboard_add_component(name="Orphan", id="X-001")
        assert "error" in result


class TestGetComponent:
    def test_get_existing_component(self):
        forgeboard_create_project(name="Get Test")
        forgeboard_add_component(name="Pole", id="POLE-001", mass_g=200.0)
        result = forgeboard_get_component(component_id="POLE-001")
        assert "error" not in result
        assert result["name"] == "Pole"
        assert result["mass_g"] == 200.0

    def test_get_missing_component_returns_error(self):
        forgeboard_create_project(name="Missing Test")
        result = forgeboard_get_component(component_id="NONEXISTENT")
        assert "error" in result


class TestRemoveComponent:
    def test_remove_existing(self):
        forgeboard_create_project(name="Remove Test")
        forgeboard_add_component(name="Part", id="PART-001")
        result = forgeboard_remove_component(component_id="PART-001")
        assert "error" not in result
        assert result["status"] == "removed"

    def test_remove_missing_returns_error(self):
        forgeboard_create_project(name="Remove Fail")
        result = forgeboard_remove_component(component_id="GHOST")
        assert "error" in result


class TestListComponents:
    def test_list_all(self):
        forgeboard_create_project(name="List Test")
        forgeboard_add_component(name="A", id="A-001", category="structure")
        forgeboard_add_component(name="B", id="B-001", category="electronics")
        result = forgeboard_list_components()
        assert "error" not in result
        assert result["count"] == 2
        ids = [c["id"] for c in result["components"]]
        assert "A-001" in ids
        assert "B-001" in ids

    def test_list_filtered_by_category(self):
        forgeboard_create_project(name="Filter Test")
        forgeboard_add_component(name="A", id="A-001", category="structure")
        forgeboard_add_component(name="B", id="B-001", category="electronics")
        result = forgeboard_list_components(category="structure")
        assert "error" not in result
        assert result["count"] == 1
        assert result["components"][0]["id"] == "A-001"


class TestUpdateComponent:
    def test_update_triggers_cascade(self):
        forgeboard_create_project(name="Cascade Test")
        forgeboard_add_component(
            name="Pole",
            id="POLE-001",
            dimensions={"outer_diameter": 30.0},
        )
        result = forgeboard_update_component(
            component_id="POLE-001",
            changes={"dimensions.outer_diameter": 35.0},
        )
        assert "error" not in result
        assert result["source_component"] == "POLE-001"


# ===========================================================================
# ASSEMBLY
# ===========================================================================


class TestCreateAssembly:
    def test_create_assembly(self):
        forgeboard_create_project(name="Asm Test")
        result = forgeboard_create_assembly(name="Main Frame")
        assert "error" not in result
        assert result["status"] == "created"
        assert result["assembly_name"] == "Main Frame"

    def test_create_duplicate_returns_error(self):
        forgeboard_create_project(name="Dup Asm")
        forgeboard_create_assembly(name="Frame")
        result = forgeboard_create_assembly(name="Frame")
        assert "error" in result


class TestAddToAssembly:
    def test_add_part_to_assembly(self):
        forgeboard_create_project(name="Add Part Test")
        forgeboard_add_component(name="Base", id="BASE-001")
        forgeboard_create_assembly(name="Assembly")
        result = forgeboard_add_to_assembly(
            assembly_name="Assembly",
            component_id="BASE-001",
            instance_name="base_1",
            at_origin=True,
        )
        assert "error" not in result
        assert result["status"] == "added"
        assert result["at_origin"] is True
        assert result["total_parts"] == 1

    def test_add_to_nonexistent_assembly_returns_error(self):
        forgeboard_create_project(name="Bad Asm")
        forgeboard_add_component(name="Part", id="P-001")
        result = forgeboard_add_to_assembly(
            assembly_name="Ghost",
            component_id="P-001",
            instance_name="p1",
        )
        assert "error" in result

    def test_add_nonexistent_component_returns_error(self):
        forgeboard_create_project(name="Bad Comp")
        forgeboard_create_assembly(name="Asm")
        result = forgeboard_add_to_assembly(
            assembly_name="Asm",
            component_id="GHOST-001",
            instance_name="g1",
        )
        assert "error" in result


class TestValidateAssembly:
    def test_validate_empty_assembly(self):
        forgeboard_create_project(name="Validate Test")
        forgeboard_create_assembly(name="EmptyAsm")
        result = forgeboard_validate_assembly(assembly_name="EmptyAsm")
        # An empty assembly should still return a result (not an error from
        # the tool itself -- the solve may return empty results or an error
        # depending on engine availability).
        # We just check the tool doesn't crash.
        assert isinstance(result, dict)

    def test_validate_nonexistent_returns_error(self):
        forgeboard_create_project(name="VNE Test")
        result = forgeboard_validate_assembly(assembly_name="Nope")
        assert "error" in result


# ===========================================================================
# PROCUREMENT
# ===========================================================================


class TestSearchCOTS:
    def test_search_returns_matches_structure(self):
        result = forgeboard_search_cots(query="M5x12 socket head cap screw")
        assert "error" not in result
        assert "match_count" in result
        assert "matches" in result
        assert isinstance(result["matches"], list)


class TestBuyOrBuild:
    def test_buy_or_build_fastener(self):
        forgeboard_create_project(name="BOB Test")
        forgeboard_add_component(
            name="M5x12 Socket Head Cap Screw",
            id="SCREW-001",
            category="fasteners",
        )
        result = forgeboard_buy_or_build(component_id="SCREW-001")
        assert "error" not in result
        assert result["decision"] == "BUY"
        assert result["confidence"] > 0.5

    def test_buy_or_build_custom_bracket(self):
        forgeboard_create_project(name="BOB Bracket")
        forgeboard_add_component(
            name="Custom Motor Bracket",
            id="BRKT-001",
            category="structure",
        )
        result = forgeboard_buy_or_build(component_id="BRKT-001")
        assert "error" not in result
        assert result["decision"] == "BUILD"

    def test_buy_or_build_nonexistent_returns_error(self):
        forgeboard_create_project(name="BOB Fail")
        result = forgeboard_buy_or_build(component_id="GHOST-001")
        assert "error" in result


# ===========================================================================
# EXPORT / BOM
# ===========================================================================


class TestGenerateBOM:
    def test_generate_bom_json(self):
        forgeboard_create_project(name="BOM Test")
        forgeboard_add_component(
            name="Plate",
            id="PLATE-001",
            mass_g=50.0,
            procurement={"supplier": "McMaster", "unit_cost": 12.50},
        )
        result = forgeboard_generate_bom(format="json")
        assert "error" not in result
        assert result["total_entries"] == 1
        assert result["total_mass_g"] == 50.0
        assert result["total_cost"] == 12.50
        assert len(result["entries"]) == 1

    def test_generate_bom_markdown(self):
        forgeboard_create_project(name="BOM MD")
        forgeboard_add_component(name="Rod", id="ROD-001", mass_g=30.0)
        result = forgeboard_generate_bom(format="markdown")
        assert "error" not in result
        assert "markdown" in result

    def test_generate_bom_csv(self):
        forgeboard_create_project(name="BOM CSV")
        forgeboard_add_component(name="Pin", id="PIN-001", mass_g=5.0)
        result = forgeboard_generate_bom(format="csv")
        assert "error" not in result
        assert "csv" in result
        assert "part_name" in result["csv"]

    def test_generate_bom_invalid_format_returns_error(self):
        forgeboard_create_project(name="BOM Bad")
        result = forgeboard_generate_bom(format="xml")
        assert "error" in result


# ===========================================================================
# DESIGN ANALYSIS
# ===========================================================================


class TestAnalyzeText:
    def test_analyze_text_returns_components(self):
        result = forgeboard_analyze_text(
            description="L-bracket for NEMA 17 motor, 3mm aluminum"
        )
        assert "error" not in result
        assert "components" in result
        assert "missing_info" in result
        assert isinstance(result["components"], list)

    def test_analyze_empty_returns_missing_info(self):
        result = forgeboard_analyze_text(description="")
        assert "error" not in result
        assert len(result["missing_info"]) > 0


# ===========================================================================
# DEPENDENCY / CASCADE
# ===========================================================================


class TestPreviewChange:
    def test_preview_without_deps(self):
        forgeboard_create_project(name="Preview Test")
        forgeboard_add_component(
            name="Pole",
            id="POLE-001",
            dimensions={"outer_diameter": 30.0},
        )
        result = forgeboard_preview_change(
            component_id="POLE-001",
            changes={"dimensions.outer_diameter": 35.0},
        )
        assert "error" not in result
        assert result["source_component"] == "POLE-001"
        # No dependencies, so no affected components
        assert result["total_affected"] == 0


class TestAddDependency:
    def test_add_dependency(self):
        forgeboard_create_project(name="Dep Test")
        forgeboard_add_component(
            name="Pole", id="POLE-001",
            dimensions={"outer_diameter": 30.0},
        )
        forgeboard_add_component(
            name="Bracket", id="BRKT-001",
            dimensions={"inner_diameter": 30.2},
        )
        result = forgeboard_add_dependency(
            source="POLE-001.dimensions.outer_diameter",
            target="BRKT-001.dimensions.inner_diameter",
            formula="source + 0.2",
        )
        assert "error" not in result
        assert result["status"] == "created"
        assert result["formula"] == "source + 0.2"


# ===========================================================================
# ERROR HANDLING
# ===========================================================================


class TestErrorHandling:
    """Verify that tools return error dicts instead of raising exceptions."""

    def test_get_summary_no_project(self):
        result = forgeboard_get_project_summary()
        assert "error" in result
        assert "No project" in result["error"]

    def test_add_component_no_project(self):
        result = forgeboard_add_component(name="X", id="X-001")
        assert "error" in result

    def test_create_assembly_no_project(self):
        result = forgeboard_create_assembly(name="Asm")
        assert "error" in result

    def test_validate_assembly_no_project(self):
        result = forgeboard_validate_assembly(assembly_name="Asm")
        assert "error" in result

    def test_generate_bom_no_project(self):
        result = forgeboard_generate_bom()
        assert "error" in result

    def test_update_component_no_project(self):
        result = forgeboard_update_component(
            component_id="X", changes={"mass_g": 10}
        )
        assert "error" in result

    def test_preview_change_no_project(self):
        result = forgeboard_preview_change(
            component_id="X", changes={"mass_g": 10}
        )
        assert "error" in result

    def test_add_dependency_no_project(self):
        result = forgeboard_add_dependency(source="a.b", target="c.d")
        assert "error" in result

    def test_buy_or_build_no_project(self):
        result = forgeboard_buy_or_build(component_id="X-001")
        assert "error" in result


# ===========================================================================
# SERIALIZATION
# ===========================================================================


class TestSerialization:
    """Verify all tool outputs are JSON-serializable dicts."""

    def test_all_returns_are_dicts(self):
        """Smoke test: every tool returns a dict (not a Pydantic model, etc.)."""
        # Without a project
        assert isinstance(forgeboard_get_project_summary(), dict)
        assert isinstance(forgeboard_create_project(name="Ser Test"), dict)
        assert isinstance(
            forgeboard_add_component(name="P", id="P-001"), dict
        )
        assert isinstance(
            forgeboard_get_component(component_id="P-001"), dict
        )
        assert isinstance(forgeboard_list_components(), dict)
        assert isinstance(forgeboard_generate_bom(), dict)
        assert isinstance(
            forgeboard_search_cots(query="M5 screw"), dict
        )
        assert isinstance(
            forgeboard_analyze_text(description="bracket"), dict
        )

    def test_dict_is_json_serializable(self):
        """Verify the output can be round-tripped through JSON."""
        import json

        forgeboard_create_project(name="JSON Test")
        forgeboard_add_component(
            name="Rod",
            id="ROD-001",
            mass_g=25.0,
            dimensions={"length_mm": 200, "diameter_mm": 10},
        )
        result = forgeboard_get_component(component_id="ROD-001")
        # This will raise if anything is not serializable
        serialized = json.dumps(result)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["name"] == "Rod"
