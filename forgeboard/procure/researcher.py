"""COTS component research and buy-vs-build decision engine.

The :class:`COTSResearcher` analyzes a :class:`~forgeboard.core.types.ComponentSpec`
and decides whether it should be purchased off-the-shelf (COTS) or custom-built.
The decision follows a deterministic rule tree for well-known component types,
falling back to provider search and LLM-assisted analysis for ambiguous cases.

Decision hierarchy:

1. **Standard fasteners** (M-series screws, nuts, washers) -- always BUY.
2. **Standard motors** (NEMA stepper, hobby servo, BLDC) -- always BUY.
3. **Standard electronics** (Arduino, Jetson, RPi, batteries) -- always BUY.
4. **Standard sensors** (IMU, barometer, GPS module) -- always BUY.
5. **Custom structural** (brackets, housings, frames, enclosures) -- usually BUILD.
6. **Ambiguous** -- search providers, compare cost/availability, decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from forgeboard.core.types import ComponentSpec
from forgeboard.procure.provider import ProductMatch, SearchFilters
from forgeboard.procure.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


class Decision(str, Enum):
    """Buy-vs-build decision outcome."""

    BUY = "BUY"
    BUILD = "BUILD"
    EITHER = "EITHER"


@dataclass
class BuyBuildDecision:
    """Result of a buy-vs-build analysis for a single component.

    Attributes:
        decision: The recommended action (BUY, BUILD, or EITHER).
        confidence: Confidence in the recommendation, 0.0 to 1.0.
        reasoning: Human-readable explanation of the decision.
        matches: Product matches found if decision is BUY or EITHER.
        estimated_build_cost: Rough cost to custom-build the part (USD).
        estimated_buy_cost: Rough cost to purchase the part (USD).
    """

    decision: Decision
    confidence: float = 0.0
    reasoning: str = ""
    matches: list[ProductMatch] = field(default_factory=list)
    estimated_build_cost: float = 0.0
    estimated_buy_cost: float = 0.0


@dataclass
class ComparisonReport:
    """Side-by-side comparison of multiple product options.

    Attributes:
        options: All product matches being compared.
        recommended: The top recommended option, or ``None``.
        reasoning: Explanation of the recommendation.
    """

    options: list[ProductMatch] = field(default_factory=list)
    recommended: ProductMatch | None = None
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------

# Regex patterns for component name/description matching.
# These are intentionally broad to catch common naming variations.

_FASTENER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bM\d+\b", re.IGNORECASE),           # M3, M4, M5, etc.
    re.compile(r"\bscrew\b", re.IGNORECASE),
    re.compile(r"\bbolt\b", re.IGNORECASE),
    re.compile(r"\bnut\b", re.IGNORECASE),
    re.compile(r"\bwasher\b", re.IGNORECASE),
    re.compile(r"\brivet\b", re.IGNORECASE),
    re.compile(r"\bstandoff\b", re.IGNORECASE),
    re.compile(r"\binsert\b", re.IGNORECASE),
    re.compile(r"\bthreat[- ]?insert\b", re.IGNORECASE),
]

_MOTOR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bNEMA\s*\d+\b", re.IGNORECASE),     # NEMA17, NEMA23
    re.compile(r"\bstepper\b", re.IGNORECASE),
    re.compile(r"\bservo\b", re.IGNORECASE),
    re.compile(r"\bBLDC\b", re.IGNORECASE),
    re.compile(r"\bbrushless\s+motor\b", re.IGNORECASE),
    re.compile(r"\bDC\s+motor\b", re.IGNORECASE),
    re.compile(r"\bgear\s*motor\b", re.IGNORECASE),
]

_ELECTRONICS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bArduino\b", re.IGNORECASE),
    re.compile(r"\bJetson\b", re.IGNORECASE),
    re.compile(r"\bRaspberry\s*Pi\b", re.IGNORECASE),
    re.compile(r"\bESP32\b", re.IGNORECASE),
    re.compile(r"\bESP8266\b", re.IGNORECASE),
    re.compile(r"\bSTM32\b", re.IGNORECASE),
    re.compile(r"\bbattery\b", re.IGNORECASE),
    re.compile(r"\bLiPo\b", re.IGNORECASE),
    re.compile(r"\bpower\s+supply\b", re.IGNORECASE),
    re.compile(r"\bvoltage\s+regulator\b", re.IGNORECASE),
    re.compile(r"\bcapacitor\b", re.IGNORECASE),
    re.compile(r"\bresistor\b", re.IGNORECASE),
    re.compile(r"\bLED\b"),
    re.compile(r"\bPCB\b"),
    re.compile(r"\bconnector\b", re.IGNORECASE),
]

_SENSOR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bIMU\b"),
    re.compile(r"\baccelerometer\b", re.IGNORECASE),
    re.compile(r"\bgyroscope\b", re.IGNORECASE),
    re.compile(r"\bbarometer\b", re.IGNORECASE),
    re.compile(r"\bGPS\b"),
    re.compile(r"\bGNSS\b"),
    re.compile(r"\blidar\b", re.IGNORECASE),
    re.compile(r"\bradar\s+module\b", re.IGNORECASE),
    re.compile(r"\bcamera\s+module\b", re.IGNORECASE),
    re.compile(r"\btemperature\s+sensor\b", re.IGNORECASE),
    re.compile(r"\bproximity\s+sensor\b", re.IGNORECASE),
    re.compile(r"\bmicrophone\b", re.IGNORECASE),
]

_CUSTOM_BUILD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bbracket\b", re.IGNORECASE),
    re.compile(r"\bhousing\b", re.IGNORECASE),
    re.compile(r"\benclosure\b", re.IGNORECASE),
    re.compile(r"\bframe\b", re.IGNORECASE),
    re.compile(r"\bchassis\b", re.IGNORECASE),
    re.compile(r"\bmount\b", re.IGNORECASE),
    re.compile(r"\badapter\s*plate\b", re.IGNORECASE),
    re.compile(r"\bcustom\b", re.IGNORECASE),
    re.compile(r"\bfairing\b", re.IGNORECASE),
    re.compile(r"\bshroud\b", re.IGNORECASE),
    re.compile(r"\bfuselage\b", re.IGNORECASE),
]


def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    """Return True if *text* matches any of the given patterns."""
    return any(p.search(text) for p in patterns)


def _classify_component(spec: ComponentSpec) -> str:
    """Classify a component into a known category for buy/build decision.

    Returns one of: 'fastener', 'motor', 'electronics', 'sensor',
    'custom_build', or 'unknown'.
    """
    # Combine name, description, and category for matching.
    searchable = f"{spec.name} {spec.description} {spec.category}"

    if _matches_any(searchable, _FASTENER_PATTERNS):
        return "fastener"
    if _matches_any(searchable, _MOTOR_PATTERNS):
        return "motor"
    if _matches_any(searchable, _ELECTRONICS_PATTERNS):
        return "electronics"
    if _matches_any(searchable, _SENSOR_PATTERNS):
        return "sensor"
    if _matches_any(searchable, _CUSTOM_BUILD_PATTERNS):
        return "custom_build"
    return "unknown"


# ---------------------------------------------------------------------------
# LLM interface (optional)
# ---------------------------------------------------------------------------


@runtime_checkable
class _LLMBackend(Protocol):
    """Minimal LLM interface for ambiguous-case analysis."""

    def generate(self, prompt: str, system: str = "") -> str: ...


# ---------------------------------------------------------------------------
# COTS Researcher
# ---------------------------------------------------------------------------


class COTSResearcher:
    """Researches whether a component should be bought (COTS) or custom-built.

    Uses a deterministic rule tree for well-known component types and falls
    back to provider search + optional LLM analysis for ambiguous cases.

    Args:
        provider_registry: The :class:`ProviderRegistry` to search for products.
        llm: Optional LLM backend for ambiguous-case analysis.
    """

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        llm: _LLMBackend | None = None,
    ) -> None:
        self._registry = provider_registry
        self._llm = llm

    def should_buy_or_build(self, spec: ComponentSpec) -> BuyBuildDecision:
        """Decide if a component should be purchased or custom-made.

        Decision tree:

        1. If ``spec.is_cots`` is already True, return BUY immediately.
        2. Standard fasteners -- always BUY (confidence 0.95).
        3. Standard motors -- always BUY (confidence 0.90).
        4. Standard electronics -- always BUY (confidence 0.90).
        5. Standard sensors -- always BUY (confidence 0.90).
        6. Custom structural -- usually BUILD (confidence 0.85).
        7. Otherwise, search providers and decide based on results.

        Args:
            spec: The component specification to analyze.

        Returns:
            A :class:`BuyBuildDecision` with reasoning.
        """
        # Pre-classified as COTS by the spec author.
        if spec.is_cots:
            matches = self._search_for_spec(spec)
            buy_cost = min((m.price for m in matches if m.price > 0), default=0.0)
            return BuyBuildDecision(
                decision=Decision.BUY,
                confidence=0.95,
                reasoning=f"Component '{spec.name}' is marked as COTS in the specification.",
                matches=matches,
                estimated_buy_cost=buy_cost,
            )

        classification = _classify_component(spec)

        if classification == "fastener":
            matches = self._search_for_spec(spec, category="fasteners")
            return BuyBuildDecision(
                decision=Decision.BUY,
                confidence=0.95,
                reasoning=(
                    f"'{spec.name}' is a standard fastener. "
                    "Standard fasteners should always be purchased, never custom-made."
                ),
                matches=matches,
                estimated_buy_cost=_cheapest_price(matches),
            )

        if classification == "motor":
            matches = self._search_for_spec(spec, category="motors")
            return BuyBuildDecision(
                decision=Decision.BUY,
                confidence=0.90,
                reasoning=(
                    f"'{spec.name}' is a standard motor. "
                    "Motors are commodity components available from multiple suppliers."
                ),
                matches=matches,
                estimated_buy_cost=_cheapest_price(matches),
            )

        if classification == "electronics":
            matches = self._search_for_spec(spec, category="electronics")
            return BuyBuildDecision(
                decision=Decision.BUY,
                confidence=0.90,
                reasoning=(
                    f"'{spec.name}' is a standard electronic component. "
                    "Electronic components should be purchased from authorized distributors."
                ),
                matches=matches,
                estimated_buy_cost=_cheapest_price(matches),
            )

        if classification == "sensor":
            matches = self._search_for_spec(spec, category="sensors")
            return BuyBuildDecision(
                decision=Decision.BUY,
                confidence=0.90,
                reasoning=(
                    f"'{spec.name}' is a standard sensor. "
                    "Sensors are precision components best sourced from manufacturers."
                ),
                matches=matches,
                estimated_buy_cost=_cheapest_price(matches),
            )

        if classification == "custom_build":
            return BuyBuildDecision(
                decision=Decision.BUILD,
                confidence=0.85,
                reasoning=(
                    f"'{spec.name}' appears to be a custom structural/mechanical part. "
                    "Custom brackets, housings, and frames are typically fabricated to "
                    "project-specific dimensions using CNC, 3D printing, or sheet metal."
                ),
                matches=[],
                estimated_build_cost=0.0,  # Caller should use bom.costing for estimate.
            )

        # Unknown classification -- search and analyze.
        return self._analyze_ambiguous(spec)

    def find_alternatives(self, spec: ComponentSpec) -> list[ProductMatch]:
        """Find purchasable alternatives for a component.

        Searches all relevant providers using the component's name and
        category.

        Args:
            spec: The component to find alternatives for.

        Returns:
            List of :class:`ProductMatch` objects sorted by confidence.
        """
        matches = self._search_for_spec(spec)
        return sorted(matches, key=lambda m: m.confidence, reverse=True)

    def compare_options(self, matches: list[ProductMatch]) -> ComparisonReport:
        """Compare multiple product options on price, availability, and specs.

        Recommends the best option based on a weighted score of:
        - Price (lower is better)
        - Availability (in-stock preferred)
        - Lead time (shorter is better)
        - Confidence (higher is better)

        Args:
            matches: Product matches to compare.

        Returns:
            A :class:`ComparisonReport` with the recommended option.
        """
        if not matches:
            return ComparisonReport(
                options=[],
                recommended=None,
                reasoning="No product matches to compare.",
            )

        if len(matches) == 1:
            return ComparisonReport(
                options=matches,
                recommended=matches[0],
                reasoning=f"Only one option available: {matches[0].name} from {matches[0].supplier}.",
            )

        # Score each match.
        scored: list[tuple[float, ProductMatch]] = []
        for match in matches:
            score = _score_match(match)
            scored.append((score, match))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_match = scored[0]

        reasoning_parts = [
            f"Recommended: {best_match.name} from {best_match.supplier}.",
        ]
        if best_match.price > 0:
            reasoning_parts.append(f"Price: ${best_match.price:.2f} {best_match.currency}.")
        if best_match.in_stock:
            reasoning_parts.append("In stock.")
        if best_match.lead_time_days > 0:
            reasoning_parts.append(f"Lead time: {best_match.lead_time_days} days.")
        reasoning_parts.append(
            f"Selected from {len(matches)} options based on weighted "
            f"price/availability/confidence scoring."
        )

        return ComparisonReport(
            options=[m for _, m in scored],
            recommended=best_match,
            reasoning=" ".join(reasoning_parts),
        )

    # -- Internal helpers ----------------------------------------------------

    def _search_for_spec(
        self, spec: ComponentSpec, category: str | None = None
    ) -> list[ProductMatch]:
        """Search providers for a component spec."""
        query = spec.name
        if spec.description:
            query = f"{spec.name} {spec.description}"

        search_category = category or spec.category or None

        filters = SearchFilters(
            category=search_category or "",
            in_stock_only=False,
        )
        return self._registry.search_all(query, category=search_category, filters=filters)

    def _analyze_ambiguous(self, spec: ComponentSpec) -> BuyBuildDecision:
        """Handle ambiguous components that do not match known categories.

        Searches providers first; if matches are found with reasonable
        confidence, recommends BUY.  Otherwise recommends EITHER.
        """
        matches = self._search_for_spec(spec)

        high_confidence = [m for m in matches if m.confidence >= 0.6]
        if high_confidence:
            buy_cost = _cheapest_price(high_confidence)
            return BuyBuildDecision(
                decision=Decision.BUY,
                confidence=0.60,
                reasoning=(
                    f"'{spec.name}' does not match a known component category, "
                    f"but {len(high_confidence)} product match(es) were found "
                    "with reasonable confidence. Purchasing is recommended."
                ),
                matches=high_confidence,
                estimated_buy_cost=buy_cost,
            )

        if matches:
            return BuyBuildDecision(
                decision=Decision.EITHER,
                confidence=0.40,
                reasoning=(
                    f"'{spec.name}' does not clearly fit a standard category. "
                    f"{len(matches)} product match(es) found but with low confidence. "
                    "Consider both purchasing and custom fabrication."
                ),
                matches=matches,
                estimated_buy_cost=_cheapest_price(matches),
            )

        return BuyBuildDecision(
            decision=Decision.EITHER,
            confidence=0.30,
            reasoning=(
                f"'{spec.name}' does not match any known category and no "
                "supplier matches were found. Manual research recommended."
            ),
            matches=[],
        )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _cheapest_price(matches: list[ProductMatch]) -> float:
    """Return the lowest positive price from a list of matches, or 0.0."""
    prices = [m.price for m in matches if m.price > 0]
    return min(prices, default=0.0)


def _score_match(match: ProductMatch) -> float:
    """Score a product match for comparison ranking.

    Higher is better.  Weights:
    - Confidence: 40%
    - In-stock bonus: 25%
    - Price competitiveness: 20% (lower relative price scores higher)
    - Lead time: 15% (shorter scores higher)
    """
    score = 0.0

    # Confidence (0.0 - 1.0 -> 0.0 - 0.40)
    score += match.confidence * 0.40

    # In-stock bonus
    if match.in_stock:
        score += 0.25

    # Price scoring: normalize against a $100 baseline (arbitrary).
    # A $10 item scores higher than a $200 item.
    if match.price > 0:
        price_score = max(0.0, 1.0 - (match.price / 100.0))
        score += price_score * 0.20
    else:
        # Unknown price gets a neutral score.
        score += 0.10

    # Lead time scoring: 0 days = perfect, 30+ days = zero.
    if match.lead_time_days <= 0:
        score += 0.15
    elif match.lead_time_days < 30:
        score += 0.15 * (1.0 - match.lead_time_days / 30.0)

    return score
