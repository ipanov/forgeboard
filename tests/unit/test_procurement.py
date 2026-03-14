"""Tests for the procurement module.

Covers:
- ProviderRegistry location-aware ordering (local first).
- Region grouping (Balkans, EU, North America).
- search_all aggregation across multiple providers.
- COTSResearcher buy/build decisions for standard fasteners.
- COTSResearcher buy/build decisions for custom brackets.
- COTSResearcher handling of ambiguous components.
- ComparisonReport generation.
"""

from __future__ import annotations

import pytest

from forgeboard.core.types import ComponentSpec
from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
)
from forgeboard.procure.registry import ProviderRegistry
from forgeboard.procure.researcher import (
    COTSResearcher,
    ComparisonReport,
    Decision,
)


# ---------------------------------------------------------------------------
# Test fixtures: stub providers
# ---------------------------------------------------------------------------


class StubProvider:
    """Minimal SupplierProvider implementation for testing.

    Args:
        provider_name: Value returned by the ``name`` property.
        provider_regions: Value returned by the ``regions`` property.
        provider_categories: Value returned by the ``categories`` property.
        results: Product matches returned by ``search()``.
    """

    def __init__(
        self,
        provider_name: str,
        provider_regions: list[str],
        provider_categories: list[str] | None = None,
        results: list[ProductMatch] | None = None,
    ) -> None:
        self._name = provider_name
        self._regions = provider_regions
        self._categories = provider_categories or []
        self._results = results or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def regions(self) -> list[str]:
        return self._regions

    @property
    def categories(self) -> list[str]:
        return self._categories

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        return self._results

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        return PriceQuote(product_id=product_id, unit_price=1.0)

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        return AvailabilityInfo(product_id=product_id, in_stock=True)


class ErrorProvider(StubProvider):
    """Provider that raises an exception on search() to test error handling."""

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        raise RuntimeError("Simulated provider failure")


# ---------------------------------------------------------------------------
# ProviderRegistry: location ordering
# ---------------------------------------------------------------------------


class TestProviderRegistryOrdering:
    """Verify that get_providers() returns local providers first."""

    def test_us_user_gets_us_provider_first(self) -> None:
        registry = ProviderRegistry(user_country="US")

        us_provider = StubProvider("McMaster", ["US"], ["fasteners"])
        eu_provider = StubProvider("Farnell", ["EU"], ["electronics"])
        global_provider = StubProvider("AliExpress", ["GLOBAL"], ["general"])

        registry.register(global_provider)
        registry.register(eu_provider)
        registry.register(us_provider)

        providers = registry.get_providers()
        names = [p.name for p in providers]

        # US provider should come first, then EU (unrelated region -> tier 3),
        # then GLOBAL (tier 2).  Wait -- GLOBAL is tier 2, unrelated is tier 3.
        # So order: McMaster (tier 0), AliExpress (tier 2), Farnell (tier 3).
        assert names[0] == "McMaster"
        assert "AliExpress" in names
        assert "Farnell" in names

    def test_mk_user_gets_balkans_provider_first(self) -> None:
        """A North Macedonian user should see Balkans/regional providers first."""
        registry = ProviderRegistry(user_country="MK")

        mk_provider = StubProvider("Local (MK)", ["MK"])
        rs_provider = StubProvider("Serbian Shop", ["RS"])
        us_provider = StubProvider("McMaster", ["US"], ["fasteners"])
        global_provider = StubProvider("AliExpress", ["GLOBAL"])

        registry.register(us_provider)
        registry.register(global_provider)
        registry.register(rs_provider)
        registry.register(mk_provider)

        providers = registry.get_providers()
        names = [p.name for p in providers]

        # MK exact match = tier 0, RS in same Balkans group = tier 1,
        # GLOBAL = tier 2, US unrelated = tier 3.
        assert names[0] == "Local (MK)"
        assert names[1] == "Serbian Shop"
        assert names.index("AliExpress") < names.index("McMaster")

    def test_de_user_gets_eu_providers_first(self) -> None:
        """A German user should see EU providers before global ones."""
        registry = ProviderRegistry(user_country="DE")

        de_provider = StubProvider("Reichelt", ["DE"], ["electronics"])
        eu_provider = StubProvider("Farnell", ["EU"], ["electronics"])
        global_provider = StubProvider("AliExpress", ["GLOBAL"])

        registry.register(global_provider)
        registry.register(eu_provider)
        registry.register(de_provider)

        providers = registry.get_providers()
        names = [p.name for p in providers]

        assert names[0] == "Reichelt"  # Tier 0: exact country match
        assert names[1] == "Farnell"   # Tier 1: EU region group match
        assert names[2] == "AliExpress"  # Tier 2: GLOBAL

    def test_category_filtering(self) -> None:
        """Only providers matching the requested category should be returned."""
        registry = ProviderRegistry(user_country="US")

        electronics = StubProvider("DigiKey", ["US"], ["electronics"])
        fasteners = StubProvider("McMaster", ["US"], ["fasteners"])
        everything = StubProvider("GenericWeb", ["GLOBAL"], [])  # empty = all

        registry.register(electronics)
        registry.register(fasteners)
        registry.register(everything)

        electronics_providers = registry.get_providers(category="electronics")
        names = [p.name for p in electronics_providers]

        assert "DigiKey" in names
        assert "GenericWeb" in names  # empty categories = handles everything
        assert "McMaster" not in names

    def test_duplicate_registration_ignored(self) -> None:
        """Registering the same provider twice should be silently ignored."""
        registry = ProviderRegistry(user_country="US")
        provider = StubProvider("DigiKey", ["US"])

        registry.register(provider)
        registry.register(provider)

        assert len(registry.get_providers()) == 1


# ---------------------------------------------------------------------------
# ProviderRegistry: region groupings
# ---------------------------------------------------------------------------


class TestRegionGroupings:
    """Verify that regional affinity groups work correctly."""

    def test_balkans_group_mutual_affinity(self) -> None:
        """Countries in the Balkans group should consider each other regional."""
        registry = ProviderRegistry(user_country="RS")  # Serbia

        bg_provider = StubProvider("BG Shop", ["BG"])  # Bulgaria
        gr_provider = StubProvider("GR Shop", ["GR"])  # Greece
        jp_provider = StubProvider("JP Shop", ["JP"])  # Japan (unrelated)

        registry.register(jp_provider)
        registry.register(gr_provider)
        registry.register(bg_provider)

        providers = registry.get_providers()
        names = [p.name for p in providers]

        # BG and GR are in Balkans group with RS -> tier 1.
        # JP is unrelated -> tier 3.
        assert names.index("BG Shop") < names.index("JP Shop")
        assert names.index("GR Shop") < names.index("JP Shop")

    def test_north_america_group(self) -> None:
        """US and CA should be in the same group."""
        registry = ProviderRegistry(user_country="CA")

        us_provider = StubProvider("McMaster", ["US"])
        de_provider = StubProvider("Reichelt", ["DE"])

        registry.register(de_provider)
        registry.register(us_provider)

        providers = registry.get_providers()
        names = [p.name for p in providers]

        # US is in NORTH_AMERICA with CA -> tier 1.
        # DE is unrelated -> tier 3.
        assert names.index("McMaster") < names.index("Reichelt")

    def test_eu_group_provider_listing_eu(self) -> None:
        """A provider listing 'EU' as a region should match EU-country users."""
        registry = ProviderRegistry(user_country="FR")

        eu_provider = StubProvider("Farnell", ["EU"])  # "EU" is a group name
        us_provider = StubProvider("McMaster", ["US"])

        registry.register(us_provider)
        registry.register(eu_provider)

        providers = registry.get_providers()
        names = [p.name for p in providers]

        # FR is in the EU group, and Farnell lists "EU" -> tier 1.
        # US is unrelated -> tier 3.
        assert names[0] == "Farnell"


# ---------------------------------------------------------------------------
# ProviderRegistry: search_all
# ---------------------------------------------------------------------------


class TestSearchAll:
    """Verify that search_all aggregates results across providers."""

    def test_aggregates_results_in_priority_order(self) -> None:
        """Results from local providers should appear before global ones."""
        local_match = ProductMatch(
            product_id="LOCAL-001",
            name="Local M3 Screw",
            supplier="Local Shop",
            price=0.10,
            confidence=0.8,
        )
        global_match = ProductMatch(
            product_id="GLOBAL-001",
            name="AliExpress M3 Screw",
            supplier="AliExpress",
            price=0.02,
            confidence=0.7,
        )

        registry = ProviderRegistry(user_country="US")
        registry.register(StubProvider("AliExpress", ["GLOBAL"], results=[global_match]))
        registry.register(StubProvider("Local", ["US"], results=[local_match]))

        results = registry.search_all("M3 screw")

        assert len(results) == 2
        # Local results come first because the US provider is queried first.
        assert results[0].product_id == "LOCAL-001"
        assert results[1].product_id == "GLOBAL-001"

    def test_handles_provider_errors_gracefully(self) -> None:
        """If one provider raises, the others still return results."""
        good_match = ProductMatch(
            product_id="GOOD-001",
            name="Working Result",
            supplier="GoodProvider",
        )

        registry = ProviderRegistry(user_country="US")
        registry.register(ErrorProvider("Broken", ["US"]))
        registry.register(StubProvider("Good", ["US"], results=[good_match]))

        results = registry.search_all("test query")

        assert len(results) == 1
        assert results[0].product_id == "GOOD-001"

    def test_empty_when_no_providers(self) -> None:
        """search_all on an empty registry returns empty list."""
        registry = ProviderRegistry(user_country="US")
        results = registry.search_all("anything")
        assert results == []

    def test_category_filter_in_search_all(self) -> None:
        """search_all with a category should only query matching providers."""
        elec_match = ProductMatch(
            product_id="E-001", name="Resistor", supplier="DigiKey"
        )
        mech_match = ProductMatch(
            product_id="M-001", name="Bolt", supplier="McMaster"
        )

        registry = ProviderRegistry(user_country="US")
        registry.register(
            StubProvider("DigiKey", ["US"], ["electronics"], results=[elec_match])
        )
        registry.register(
            StubProvider("McMaster", ["US"], ["fasteners"], results=[mech_match])
        )

        results = registry.search_all("component", category="electronics")

        assert len(results) == 1
        assert results[0].product_id == "E-001"


# ---------------------------------------------------------------------------
# COTSResearcher: buy/build decisions
# ---------------------------------------------------------------------------


class TestBuyBuildDecision:
    """Test the deterministic rules in COTSResearcher.should_buy_or_build()."""

    @pytest.fixture()
    def researcher(self) -> COTSResearcher:
        """Create a researcher with an empty registry (no search results)."""
        registry = ProviderRegistry(user_country="US")
        return COTSResearcher(provider_registry=registry)

    def test_standard_fastener_always_buy(self, researcher: COTSResearcher) -> None:
        """M3 screws, nuts, bolts should always be BUY."""
        spec = ComponentSpec(
            name="M3x10 Socket Head Cap Screw",
            id="FAST-001",
            category="fasteners",
            description="Stainless steel M3x10mm socket head cap screw",
        )
        decision = researcher.should_buy_or_build(spec)

        assert decision.decision == Decision.BUY
        assert decision.confidence >= 0.9
        assert "fastener" in decision.reasoning.lower()

    def test_bolt_is_fastener(self, researcher: COTSResearcher) -> None:
        """A bolt should be classified as a fastener and recommended to BUY."""
        spec = ComponentSpec(
            name="Hex Bolt M5x20",
            id="FAST-002",
            category="hardware",
        )
        decision = researcher.should_buy_or_build(spec)

        assert decision.decision == Decision.BUY
        assert decision.confidence >= 0.9

    def test_washer_is_fastener(self, researcher: COTSResearcher) -> None:
        """A washer should be classified as a fastener."""
        spec = ComponentSpec(
            name="M4 Flat Washer",
            id="FAST-003",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUY

    def test_nema17_motor_always_buy(self, researcher: COTSResearcher) -> None:
        """NEMA17 stepper motors should always be BUY."""
        spec = ComponentSpec(
            name="NEMA17 Stepper Motor",
            id="MOT-001",
            category="motors",
            description="1.8 degree step angle, 0.4Nm holding torque",
        )
        decision = researcher.should_buy_or_build(spec)

        assert decision.decision == Decision.BUY
        assert decision.confidence >= 0.85
        assert "motor" in decision.reasoning.lower()

    def test_servo_always_buy(self, researcher: COTSResearcher) -> None:
        """Hobby servos should be BUY."""
        spec = ComponentSpec(
            name="SG90 Micro Servo",
            id="MOT-002",
            category="actuators",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUY

    def test_arduino_always_buy(self, researcher: COTSResearcher) -> None:
        """Arduino boards should always be BUY."""
        spec = ComponentSpec(
            name="Arduino Mega 2560",
            id="ELEC-001",
            category="electronics",
        )
        decision = researcher.should_buy_or_build(spec)

        assert decision.decision == Decision.BUY
        assert decision.confidence >= 0.85

    def test_jetson_always_buy(self, researcher: COTSResearcher) -> None:
        """NVIDIA Jetson modules should always be BUY."""
        spec = ComponentSpec(
            name="Jetson Orin Nano",
            id="ELEC-002",
            category="electronics",
            description="NVIDIA Jetson Orin Nano 8GB module",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUY

    def test_battery_always_buy(self, researcher: COTSResearcher) -> None:
        """Batteries should always be BUY."""
        spec = ComponentSpec(
            name="6S LiPo Battery 5000mAh",
            id="ELEC-003",
            category="power",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUY

    def test_imu_sensor_always_buy(self, researcher: COTSResearcher) -> None:
        """IMU sensor modules should be BUY."""
        spec = ComponentSpec(
            name="BMI088 IMU Module",
            id="SENS-001",
            category="sensors",
            description="6-axis IMU with accelerometer and gyroscope",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUY

    def test_gps_module_always_buy(self, researcher: COTSResearcher) -> None:
        """GPS modules should be BUY."""
        spec = ComponentSpec(
            name="u-blox NEO-M9N GPS Module",
            id="SENS-002",
            category="sensors",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUY

    def test_custom_bracket_always_build(self, researcher: COTSResearcher) -> None:
        """Custom brackets should always be BUILD."""
        spec = ComponentSpec(
            name="Camera Mount Bracket",
            id="STRUCT-001",
            category="structure",
            description="Custom aluminum bracket for camera mounting",
        )
        decision = researcher.should_buy_or_build(spec)

        assert decision.decision == Decision.BUILD
        assert decision.confidence >= 0.8
        assert "custom" in decision.reasoning.lower() or "bracket" in decision.reasoning.lower()

    def test_custom_housing_always_build(self, researcher: COTSResearcher) -> None:
        """Custom housings/enclosures should be BUILD."""
        spec = ComponentSpec(
            name="Electronics Housing",
            id="STRUCT-002",
            category="structure",
            description="Custom ABS enclosure for electronics bay",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUILD

    def test_custom_frame_always_build(self, researcher: COTSResearcher) -> None:
        """Custom frames should be BUILD."""
        spec = ComponentSpec(
            name="Main Frame Assembly",
            id="STRUCT-003",
            category="structure",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUILD

    def test_cots_marked_spec_is_buy(self, researcher: COTSResearcher) -> None:
        """A spec already marked is_cots=True should be BUY."""
        spec = ComponentSpec(
            name="Some Generic Component",
            id="MISC-001",
            is_cots=True,
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.BUY
        assert decision.confidence >= 0.9

    def test_ambiguous_component_returns_either(self, researcher: COTSResearcher) -> None:
        """An unknown component with no matches should return EITHER."""
        spec = ComponentSpec(
            name="Quantum Entangler",
            id="MISC-002",
            category="exotic",
            description="Temporal displacement device",
        )
        decision = researcher.should_buy_or_build(spec)
        assert decision.decision == Decision.EITHER


# ---------------------------------------------------------------------------
# COTSResearcher: find_alternatives and compare_options
# ---------------------------------------------------------------------------


class TestResearcherHelpers:
    """Test find_alternatives() and compare_options()."""

    def test_find_alternatives_returns_sorted_by_confidence(self) -> None:
        """find_alternatives should return results sorted by confidence."""
        low_conf = ProductMatch(
            product_id="P1", name="Low Confidence", confidence=0.3
        )
        high_conf = ProductMatch(
            product_id="P2", name="High Confidence", confidence=0.9
        )

        registry = ProviderRegistry(user_country="US")
        registry.register(
            StubProvider("Test", ["US"], results=[low_conf, high_conf])
        )
        researcher = COTSResearcher(provider_registry=registry)

        spec = ComponentSpec(name="Test Part", id="T-001")
        alternatives = researcher.find_alternatives(spec)

        assert len(alternatives) == 2
        assert alternatives[0].confidence > alternatives[1].confidence

    def test_compare_options_recommends_best(self) -> None:
        """compare_options should recommend the highest-scored option."""
        cheap_and_stocked = ProductMatch(
            product_id="P1",
            name="Cheap and In Stock",
            price=5.0,
            in_stock=True,
            lead_time_days=2,
            confidence=0.85,
        )
        expensive_and_slow = ProductMatch(
            product_id="P2",
            name="Expensive and Slow",
            price=50.0,
            in_stock=False,
            lead_time_days=30,
            confidence=0.70,
        )

        registry = ProviderRegistry(user_country="US")
        researcher = COTSResearcher(provider_registry=registry)

        report = researcher.compare_options([cheap_and_stocked, expensive_and_slow])

        assert report.recommended is not None
        assert report.recommended.product_id == "P1"
        assert len(report.options) == 2
        assert "Cheap and In Stock" in report.reasoning

    def test_compare_options_empty_list(self) -> None:
        """compare_options with no matches returns empty report."""
        registry = ProviderRegistry(user_country="US")
        researcher = COTSResearcher(provider_registry=registry)

        report = researcher.compare_options([])

        assert report.recommended is None
        assert report.options == []

    def test_compare_options_single_match(self) -> None:
        """compare_options with one match recommends that match."""
        only_option = ProductMatch(
            product_id="P1", name="Only Option", confidence=0.5
        )

        registry = ProviderRegistry(user_country="US")
        researcher = COTSResearcher(provider_registry=registry)

        report = researcher.compare_options([only_option])

        assert report.recommended is not None
        assert report.recommended.product_id == "P1"


# ---------------------------------------------------------------------------
# Data type validation
# ---------------------------------------------------------------------------


class TestDataTypes:
    """Verify that procurement data types behave correctly."""

    def test_search_filters_defaults(self) -> None:
        """SearchFilters should have sensible defaults."""
        f = SearchFilters()
        assert f.category == ""
        assert f.min_price is None
        assert f.max_price is None
        assert f.in_stock_only is False
        assert f.country_code == ""

    def test_product_match_defaults(self) -> None:
        """ProductMatch should have sensible defaults."""
        m = ProductMatch(product_id="X", name="Test")
        assert m.price == 0.0
        assert m.currency == "USD"
        assert m.in_stock is True
        assert m.confidence == 0.0
        assert m.specs == {}

    def test_price_quote_defaults(self) -> None:
        """PriceQuote should have sensible defaults."""
        q = PriceQuote(product_id="X", unit_price=10.0)
        assert q.currency == "USD"
        assert q.quantity_breaks == []
        assert q.shipping_estimate == 0.0

    def test_availability_info_defaults(self) -> None:
        """AvailabilityInfo should have sensible defaults."""
        a = AvailabilityInfo(product_id="X")
        assert a.in_stock is False
        assert a.quantity_available == -1
        assert a.lead_time_days == 0
        assert a.warehouse_location == ""
