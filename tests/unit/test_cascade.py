"""Unit tests for the reactive cascade system.

Tests cover:
- Cascade propagation: change pole diameter -> bracket inner diameter updates
- Cascade preview does not modify state
- Cascade with formula evaluation (e.g. "source + 0.2" for clearance fit)
- Event bus publish/subscribe
- ForgeProject ties everything together
- BOM updates when component cost changes
- Mass recalculation after dimension change
"""

from __future__ import annotations

from typing import Any

import pytest

from forgeboard.bom.generator import BillOfMaterials
from forgeboard.core.cascade import (
    AffectedComponent,
    CascadeEngine,
    CascadePreview,
    CascadeResult,
    UpdateStatus,
)
from forgeboard.core.dependency_graph import DependencyGraph
from forgeboard.core.events import (
    BOM_UPDATED,
    COMPONENT_CREATED,
    COMPONENT_UPDATED,
    COST_CHANGED,
    MASS_CHANGED,
    EventBus,
)
from forgeboard.core.project import ForgeProject, MassProperties
from forgeboard.core.registry import ComponentRegistry
from forgeboard.core.types import (
    ComponentSpec,
    InterfacePoint,
    InterfaceType,
    Material,
    Vector3,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def aluminum() -> Material:
    return Material(
        name="Aluminum_6061",
        density_g_cm3=2.7,
        yield_strength_mpa=276.0,
        cost_per_kg=8.0,
    )


@pytest.fixture
def pole_spec(aluminum: Material) -> ComponentSpec:
    """Telescopic pole component."""
    return ComponentSpec(
        name="Telescopic_Pole",
        id="pole",
        description="Main vertical pole",
        category="structure",
        material=aluminum,
        dimensions={"outer_diameter": 30.0, "length": 500.0, "wall_thickness": 2.0},
        mass_g=250.0,
        procurement={"unit_cost": 15.00, "supplier": "MetalCo"},
    )


@pytest.fixture
def bracket_spec(aluminum: Material) -> ComponentSpec:
    """Mounting bracket that mates with the pole."""
    return ComponentSpec(
        name="Mounting_Bracket",
        id="bracket",
        description="Clamp bracket around pole",
        category="structure",
        material=aluminum,
        dimensions={"inner_diameter": 30.2, "width": 40.0, "height": 20.0},
        mass_g=65.0,
        procurement={"unit_cost": 8.50, "supplier": "MachineShop"},
    )


@pytest.fixture
def adapter_spec() -> ComponentSpec:
    """Adapter ring that mates with the bracket."""
    return ComponentSpec(
        name="Adapter_Ring",
        id="adapter",
        description="Adapter between bracket and sensor",
        category="structure",
        dimensions={"bore_diameter": 30.4, "outer_diameter": 50.0},
        mass_g=30.0,
        procurement={"unit_cost": 5.00},
    )


@pytest.fixture
def registry(
    pole_spec: ComponentSpec,
    bracket_spec: ComponentSpec,
    adapter_spec: ComponentSpec,
) -> ComponentRegistry:
    reg = ComponentRegistry()
    reg.add(pole_spec)
    reg.add(bracket_spec)
    reg.add(adapter_spec)
    return reg


@pytest.fixture
def graph() -> DependencyGraph:
    """Graph with a three-node chain: pole -> bracket -> adapter."""
    g = DependencyGraph()
    # When pole OD changes, bracket ID must be pole OD + 0.2 (clearance fit)
    g.add_dependency(
        "pole.dimensions.outer_diameter",
        "bracket.dimensions.inner_diameter",
        "source + 0.2",
    )
    # When bracket ID changes, adapter bore must be bracket ID + 0.2
    g.add_dependency(
        "bracket.dimensions.inner_diameter",
        "adapter.dimensions.bore_diameter",
        "source + 0.2",
    )
    return g


@pytest.fixture
def cascade_engine(
    registry: ComponentRegistry, graph: DependencyGraph
) -> CascadeEngine:
    return CascadeEngine(registry, graph)


# ---------------------------------------------------------------------------
# CascadeEngine: propagation tests
# ---------------------------------------------------------------------------


class TestCascadePropagation:
    """Test that changes propagate correctly through the dependency graph."""

    def test_single_hop_propagation(
        self, cascade_engine: CascadeEngine, registry: ComponentRegistry
    ) -> None:
        """Change pole OD -> bracket ID should update."""
        result = cascade_engine.apply_change(
            "pole", {"dimensions.outer_diameter": 35.0}
        )

        assert result.source_component == "pole"
        assert result.total_affected == 2  # bracket + adapter

        # Verify the pole was updated
        pole = registry.get("pole")
        assert pole is not None
        assert pole.dimensions["outer_diameter"] == 35.0

        # Verify bracket inner_diameter was recalculated: 35.0 + 0.2 = 35.2
        bracket = registry.get("bracket")
        assert bracket is not None
        assert bracket.dimensions["inner_diameter"] == pytest.approx(35.2)

    def test_multi_hop_propagation(
        self, cascade_engine: CascadeEngine, registry: ComponentRegistry
    ) -> None:
        """Change pole OD -> bracket ID -> adapter bore should all update."""
        result = cascade_engine.apply_change(
            "pole", {"dimensions.outer_diameter": 40.0}
        )

        # Pole OD = 40.0
        # Bracket ID = 40.0 + 0.2 = 40.2
        # Adapter bore = 40.2 + 0.2 = 40.4
        adapter = registry.get("adapter")
        assert adapter is not None
        assert adapter.dimensions["bore_diameter"] == pytest.approx(40.4)

    def test_affected_components_have_correct_old_and_new(
        self, cascade_engine: CascadeEngine
    ) -> None:
        """AffectedComponent records should capture old and new values."""
        result = cascade_engine.apply_change(
            "pole", {"dimensions.outer_diameter": 32.0}
        )

        bracket_update = next(
            ac for ac in result.affected_components if ac.component_id == "bracket"
        )
        assert bracket_update.old_value == pytest.approx(30.2)
        assert bracket_update.new_value == pytest.approx(32.2)
        assert bracket_update.formula == "source + 0.2"
        assert bracket_update.status == UpdateStatus.UPDATED

    def test_affected_components_in_topological_order(
        self, cascade_engine: CascadeEngine
    ) -> None:
        """Affected components should be in topological (dependency) order."""
        result = cascade_engine.apply_change(
            "pole", {"dimensions.outer_diameter": 33.0}
        )

        ids = [ac.component_id for ac in result.affected_components]
        assert ids == ["bracket", "adapter"]

    def test_unknown_component_raises_key_error(
        self, cascade_engine: CascadeEngine
    ) -> None:
        """Changing a non-existent component should raise KeyError."""
        with pytest.raises(KeyError, match="nonexistent"):
            cascade_engine.apply_change("nonexistent", {"x": 1})

    def test_change_with_no_downstream(
        self, cascade_engine: CascadeEngine, registry: ComponentRegistry
    ) -> None:
        """Changing a field with no dependencies should return empty affected list."""
        result = cascade_engine.apply_change(
            "adapter", {"dimensions.outer_diameter": 55.0}
        )

        assert result.total_affected == 0
        assert result.affected_components == []

        adapter = registry.get("adapter")
        assert adapter is not None
        assert adapter.dimensions["outer_diameter"] == 55.0


# ---------------------------------------------------------------------------
# CascadeEngine: preview tests
# ---------------------------------------------------------------------------


class TestCascadePreview:
    """Test that preview_change shows effects without modifying state."""

    def test_preview_returns_cascade_preview(
        self, cascade_engine: CascadeEngine
    ) -> None:
        preview = cascade_engine.preview_change(
            "pole", {"dimensions.outer_diameter": 35.0}
        )
        assert isinstance(preview, CascadePreview)
        assert preview.applied is False

    def test_preview_does_not_modify_registry(
        self,
        cascade_engine: CascadeEngine,
        registry: ComponentRegistry,
    ) -> None:
        """After preview, registry values should be unchanged."""
        # Capture original values
        pole_od_before = registry.get("pole").dimensions["outer_diameter"]
        bracket_id_before = registry.get("bracket").dimensions["inner_diameter"]
        adapter_bore_before = registry.get("adapter").dimensions["bore_diameter"]

        cascade_engine.preview_change(
            "pole", {"dimensions.outer_diameter": 50.0}
        )

        # Verify nothing changed
        assert registry.get("pole").dimensions["outer_diameter"] == pole_od_before
        assert (
            registry.get("bracket").dimensions["inner_diameter"] == bracket_id_before
        )
        assert (
            registry.get("adapter").dimensions["bore_diameter"] == adapter_bore_before
        )

    def test_preview_shows_correct_affected_values(
        self, cascade_engine: CascadeEngine
    ) -> None:
        preview = cascade_engine.preview_change(
            "pole", {"dimensions.outer_diameter": 38.0}
        )

        assert preview.total_affected == 2
        bracket_update = next(
            ac for ac in preview.affected_components if ac.component_id == "bracket"
        )
        assert bracket_update.new_value == pytest.approx(38.2)

        adapter_update = next(
            ac for ac in preview.affected_components if ac.component_id == "adapter"
        )
        assert adapter_update.new_value == pytest.approx(38.4)

    def test_preview_unknown_component_raises(
        self, cascade_engine: CascadeEngine
    ) -> None:
        with pytest.raises(KeyError):
            cascade_engine.preview_change("ghost", {"x": 1})


# ---------------------------------------------------------------------------
# CascadeEngine: formula evaluation
# ---------------------------------------------------------------------------


class TestFormulaEvaluation:
    """Test formula-based value propagation."""

    def test_identity_formula(self, registry: ComponentRegistry) -> None:
        """None/empty formula means target = source."""
        g = DependencyGraph()
        g.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            None,
        )
        engine = CascadeEngine(registry, g)
        result = engine.apply_change("pole", {"dimensions.outer_diameter": 42.0})

        bracket = registry.get("bracket")
        assert bracket.dimensions["inner_diameter"] == 42.0

    def test_clearance_fit_formula(self, cascade_engine: CascadeEngine) -> None:
        """source + 0.2 should produce a clearance fit."""
        result = cascade_engine.apply_change(
            "pole", {"dimensions.outer_diameter": 25.0}
        )

        bracket_update = next(
            ac for ac in result.affected_components if ac.component_id == "bracket"
        )
        assert bracket_update.new_value == pytest.approx(25.2)

    def test_scaling_formula(self, registry: ComponentRegistry) -> None:
        """source * 1.5 should scale the value."""
        g = DependencyGraph()
        g.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            "source * 1.5",
        )
        engine = CascadeEngine(registry, g)
        engine.apply_change("pole", {"dimensions.outer_diameter": 20.0})

        bracket = registry.get("bracket")
        assert bracket.dimensions["inner_diameter"] == pytest.approx(30.0)

    def test_max_formula(self, registry: ComponentRegistry) -> None:
        """max(source, 10) should apply a minimum floor."""
        g = DependencyGraph()
        g.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            "max(source, 10)",
        )
        engine = CascadeEngine(registry, g)

        engine.apply_change("pole", {"dimensions.outer_diameter": 5.0})
        bracket = registry.get("bracket")
        assert bracket.dimensions["inner_diameter"] == pytest.approx(10.0)

        engine.apply_change("pole", {"dimensions.outer_diameter": 15.0})
        bracket = registry.get("bracket")
        assert bracket.dimensions["inner_diameter"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# CascadeEngine: listener notification
# ---------------------------------------------------------------------------


class TestCascadeListeners:
    """Test that listeners are notified during cascade."""

    def test_listener_on_component_updated(
        self, cascade_engine: CascadeEngine
    ) -> None:
        updates: list[tuple[str, dict]] = []

        class Recorder:
            def on_component_updated(
                self, component_id: str, changes: dict[str, Any]
            ) -> None:
                updates.append((component_id, dict(changes)))

            def on_cascade_complete(self, result: CascadeResult) -> None:
                pass

        cascade_engine.register_listener(Recorder())
        cascade_engine.apply_change("pole", {"dimensions.outer_diameter": 36.0})

        # Should have been called for bracket and adapter
        updated_ids = [cid for cid, _ in updates]
        assert "bracket" in updated_ids
        assert "adapter" in updated_ids

    def test_listener_on_cascade_complete(
        self, cascade_engine: CascadeEngine
    ) -> None:
        results: list[CascadeResult] = []

        class Recorder:
            def on_component_updated(
                self, component_id: str, changes: dict[str, Any]
            ) -> None:
                pass

            def on_cascade_complete(self, result: CascadeResult) -> None:
                results.append(result)

        cascade_engine.register_listener(Recorder())
        cascade_engine.apply_change("pole", {"dimensions.outer_diameter": 37.0})

        assert len(results) == 1
        assert results[0].source_component == "pole"
        assert results[0].total_affected == 2


# ---------------------------------------------------------------------------
# EventBus tests
# ---------------------------------------------------------------------------


class TestEventBus:
    """Test the simple pub-sub event bus."""

    def test_subscribe_and_publish(self) -> None:
        bus = EventBus()
        received: list[dict] = []
        bus.subscribe("test.event", lambda data: received.append(data))
        bus.publish("test.event", {"key": "value"})
        assert len(received) == 1
        assert received[0] == {"key": "value"}

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[dict] = []
        handler = lambda data: received.append(data)
        bus.subscribe("test.event", handler)
        bus.unsubscribe("test.event", handler)
        bus.publish("test.event", {"key": "value"})
        assert len(received) == 0

    def test_multiple_handlers(self) -> None:
        bus = EventBus()
        a_received: list[dict] = []
        b_received: list[dict] = []
        bus.subscribe("ev", lambda data: a_received.append(data))
        bus.subscribe("ev", lambda data: b_received.append(data))
        bus.publish("ev", {"x": 1})
        assert len(a_received) == 1
        assert len(b_received) == 1

    def test_publish_to_nonexistent_event_is_noop(self) -> None:
        bus = EventBus()
        bus.publish("nonexistent", {"data": True})  # should not raise

    def test_handler_exception_does_not_stop_others(self) -> None:
        bus = EventBus()
        received: list[dict] = []

        def bad_handler(data: dict) -> None:
            raise RuntimeError("boom")

        def good_handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("ev", bad_handler)
        bus.subscribe("ev", good_handler)
        bus.publish("ev", {"x": 1})

        # good_handler should still have been called
        assert len(received) == 1

    def test_clear_specific_event(self) -> None:
        bus = EventBus()
        received: list[dict] = []
        bus.subscribe("a", lambda data: received.append(data))
        bus.subscribe("b", lambda data: received.append(data))
        bus.clear("a")
        bus.publish("a", {})
        bus.publish("b", {})
        assert len(received) == 1

    def test_clear_all(self) -> None:
        bus = EventBus()
        received: list[dict] = []
        bus.subscribe("a", lambda data: received.append(data))
        bus.subscribe("b", lambda data: received.append(data))
        bus.clear()
        bus.publish("a", {})
        bus.publish("b", {})
        assert len(received) == 0

    def test_handler_count(self) -> None:
        bus = EventBus()
        assert bus.handler_count == 0
        bus.subscribe("a", lambda d: None)
        bus.subscribe("b", lambda d: None)
        assert bus.handler_count == 2


# ---------------------------------------------------------------------------
# ForgeProject integration tests
# ---------------------------------------------------------------------------


class TestForgeProject:
    """Test that ForgeProject ties all systems together."""

    def test_add_and_get_component(self, pole_spec: ComponentSpec) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)

        retrieved = project.get_component("pole")
        assert retrieved is not None
        assert retrieved.name == "Telescopic_Pole"

    def test_update_triggers_cascade(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)

        project.graph.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            "source + 0.2",
        )

        result = project.update_component("pole", {"dimensions.outer_diameter": 35.0})

        assert result.total_affected == 1
        bracket = project.get_component("bracket")
        assert bracket.dimensions["inner_diameter"] == pytest.approx(35.2)

    def test_update_publishes_events(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)

        project.graph.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            "source + 0.2",
        )

        events: list[tuple[str, dict]] = []

        def recorder(data: dict) -> None:
            events.append((COMPONENT_UPDATED, data))

        project.event_bus.subscribe(COMPONENT_UPDATED, recorder)
        project.update_component("pole", {"dimensions.outer_diameter": 35.0})

        # Should have received at least one COMPONENT_UPDATED event
        assert len(events) >= 1

    def test_add_component_publishes_created_event(
        self, pole_spec: ComponentSpec
    ) -> None:
        project = ForgeProject("TestProject")
        events: list[dict] = []
        project.event_bus.subscribe(COMPONENT_CREATED, lambda d: events.append(d))
        project.add_component(pole_spec)
        assert len(events) == 1
        assert events[0]["component_id"] == "pole"

    def test_get_bom(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)

        bom = project.get_bom()
        assert isinstance(bom, BillOfMaterials)
        assert len(bom.entries) == 2
        assert bom.total_mass_g == pytest.approx(315.0)  # 250 + 65

    def test_get_mass_properties(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)

        mass = project.get_mass_properties()
        assert isinstance(mass, MassProperties)
        assert mass.total_mass_g == pytest.approx(315.0)
        assert mass.per_component["pole"] == pytest.approx(250.0)
        assert mass.per_component["bracket"] == pytest.approx(65.0)

    def test_add_assembly(self) -> None:
        project = ForgeProject("TestProject")
        asm = project.add_assembly("main_assembly")
        assert asm.name == "main_assembly"
        assert "main_assembly" in project.assemblies

    def test_add_duplicate_assembly_raises(self) -> None:
        project = ForgeProject("TestProject")
        project.add_assembly("asm1")
        with pytest.raises(ValueError, match="already exists"):
            project.add_assembly("asm1")

    def test_summary(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)

        s = project.summary
        assert "TestProject" in s
        assert "Components: 2" in s
        assert "315.0 g" in s

    def test_remove_component(self, pole_spec: ComponentSpec) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)
        assert project.remove_component("pole") is True
        assert project.get_component("pole") is None

    def test_preview_update_does_not_change_state(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("TestProject")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)

        project.graph.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            "source + 0.2",
        )

        original_bracket_id = project.get_component("bracket").dimensions[
            "inner_diameter"
        ]
        preview = project.preview_update(
            "pole", {"dimensions.outer_diameter": 99.0}
        )

        assert preview.applied is False
        assert (
            project.get_component("bracket").dimensions["inner_diameter"]
            == original_bracket_id
        )


# ---------------------------------------------------------------------------
# BOM update when cost changes
# ---------------------------------------------------------------------------


class TestBomCostCascade:
    """Test that BOM reflects cost changes after cascade."""

    def test_bom_updates_after_cost_change(
        self,
        pole_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("CostTest")
        project.add_component(pole_spec)

        bom_before = project.get_bom()
        pole_entry = next(e for e in bom_before.entries if e.part_id == "pole")
        assert pole_entry.unit_cost == pytest.approx(15.00)

        # Update the cost via procurement
        project.update_component(
            "pole", {"procurement.unit_cost": 22.00}
        )

        bom_after = project.get_bom()
        pole_entry_after = next(
            e for e in bom_after.entries if e.part_id == "pole"
        )
        assert pole_entry_after.unit_cost == pytest.approx(22.00)

    def test_cost_changed_flag(self, pole_spec: ComponentSpec) -> None:
        project = ForgeProject("CostFlagTest")
        project.add_component(pole_spec)

        result = project.update_component(
            "pole", {"procurement.unit_cost": 30.00}
        )
        assert result.cost_changed is True
        assert result.bom_changed is True


# ---------------------------------------------------------------------------
# Mass recalculation after dimension change
# ---------------------------------------------------------------------------


class TestMassRecalculation:
    """Test that mass properties update when components change."""

    def test_mass_updates_after_change(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
    ) -> None:
        project = ForgeProject("MassTest")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)

        mass_before = project.get_mass_properties()
        assert mass_before.total_mass_g == pytest.approx(315.0)

        # Change pole mass directly
        project.update_component("pole", {"mass_g": 300.0})

        mass_after = project.get_mass_properties()
        assert mass_after.total_mass_g == pytest.approx(365.0)  # 300 + 65
        assert mass_after.per_component["pole"] == pytest.approx(300.0)

    def test_mass_changed_flag(self, pole_spec: ComponentSpec) -> None:
        project = ForgeProject("MassFlagTest")
        project.add_component(pole_spec)

        result = project.update_component("pole", {"mass_g": 280.0})
        assert result.mass_changed is True

    def test_mass_events_published(self, pole_spec: ComponentSpec) -> None:
        project = ForgeProject("MassEventTest")
        project.add_component(pole_spec)

        events: list[dict] = []
        project.event_bus.subscribe(MASS_CHANGED, lambda d: events.append(d))

        project.update_component("pole", {"mass_g": 280.0})
        assert len(events) == 1
        assert events[0]["source"] == "pole"


# ---------------------------------------------------------------------------
# Persistence (save/load round-trip)
# ---------------------------------------------------------------------------


class TestProjectPersistence:
    """Test save and load round-trip."""

    def test_save_and_load(
        self,
        pole_spec: ComponentSpec,
        bracket_spec: ComponentSpec,
        tmp_path,
    ) -> None:
        project = ForgeProject("PersistTest")
        project.add_component(pole_spec)
        project.add_component(bracket_spec)
        project.graph.add_dependency(
            "pole.dimensions.outer_diameter",
            "bracket.dimensions.inner_diameter",
            "source + 0.2",
        )

        save_dir = str(tmp_path / "project_save")
        project.save(save_dir)

        loaded = ForgeProject.load(save_dir)
        assert loaded.name == "PersistTest"
        assert len(loaded.registry) == 2
        assert loaded.get_component("pole") is not None
        assert loaded.get_component("bracket") is not None

        # Graph edges should be restored
        assert len(loaded.graph.edges) == 1
        edge = loaded.graph.edges[0]
        assert edge.source == "pole.dimensions.outer_diameter"
        assert edge.target == "bracket.dimensions.inner_diameter"
        assert edge.formula == "source + 0.2"

    def test_load_nonexistent_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            ForgeProject.load(str(tmp_path / "does_not_exist"))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_cascade_deterministic(
        self, registry: ComponentRegistry, graph: DependencyGraph
    ) -> None:
        """Running the same cascade twice should produce the same result."""
        # First run
        engine1 = CascadeEngine(ComponentRegistry(), graph)
        # Populate fresh registry with same specs
        for spec in registry.list_all():
            engine1.registry.add(spec.model_copy(deep=True))

        result1 = engine1.apply_change("pole", {"dimensions.outer_diameter": 44.0})

        # Second run with fresh state
        engine2 = CascadeEngine(ComponentRegistry(), graph)
        for spec in registry.list_all():
            engine2.registry.add(spec.model_copy(deep=True))

        result2 = engine2.apply_change("pole", {"dimensions.outer_diameter": 44.0})

        # Results should be identical
        assert result1.total_affected == result2.total_affected
        for ac1, ac2 in zip(
            result1.affected_components, result2.affected_components
        ):
            assert ac1.component_id == ac2.component_id
            assert ac1.field == ac2.field
            assert ac1.new_value == ac2.new_value
            assert ac1.old_value == ac2.old_value

    def test_build_graph_from_registry_with_interfaces(self) -> None:
        """Auto-detect dependencies from matching interface names."""
        reg = ComponentRegistry()
        reg.add(
            ComponentSpec(
                name="Pole",
                id="pole",
                dimensions={"od": 30.0},
                interfaces={
                    "top_mount": InterfacePoint(
                        name="top_mount",
                        type=InterfaceType.CYLINDRICAL,
                        diameter_mm=30.0,
                    )
                },
            )
        )
        reg.add(
            ComponentSpec(
                name="Clamp",
                id="clamp",
                dimensions={"id": 30.2},
                interfaces={
                    "top_mount": InterfacePoint(
                        name="top_mount",
                        type=InterfaceType.CYLINDRICAL,
                        diameter_mm=30.2,
                    )
                },
            )
        )

        g = DependencyGraph()
        engine = CascadeEngine(reg, g)
        edges_added = engine.build_graph_from_registry()
        assert edges_added >= 1
