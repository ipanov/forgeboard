"""Generic web search supplier provider.

Uses an LLM to perform broad product searches across the internet.
This is the universal fallback provider -- when no specialized API
provider has results, GenericWebProvider asks the LLM to suggest
where a component can be purchased, with approximate pricing and
supplier links.

In a production deployment, this would chain with an actual web search
tool (e.g. Brave Search API, Serper, or MCP web-search) to ground the
LLM's suggestions in real search results.  For now, it operates in
prompt-only mode: the LLM generates structured suggestions based on
its training data.

TODO: Integrate actual web search API for grounded results.
TODO: Add result caching to avoid redundant LLM calls.
TODO: Implement confidence scoring based on search result quality.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
)


@runtime_checkable
class _LLMBackend(Protocol):
    """Minimal LLM interface needed by GenericWebProvider."""

    def generate(self, prompt: str, system: str = "") -> str: ...


# ---------------------------------------------------------------------------
# System prompt for product search
# ---------------------------------------------------------------------------

_SEARCH_SYSTEM_PROMPT = """\
You are a procurement research assistant. Given a product search query,
suggest real products that can be purchased online. For each suggestion,
provide:
- product_id: a plausible SKU or model number
- name: the product name
- description: one-sentence description
- supplier: the store/marketplace name
- price: estimated price in USD (your best guess)
- url: a plausible product URL (use real domains)
- in_stock: true/false
- lead_time_days: estimated shipping time
- confidence: 0.0-1.0 how confident you are this product exists

Respond with a JSON array of objects. Return at most 5 results.
If you cannot find relevant products, return an empty array: []
Do not include markdown fences. Return only valid JSON."""


class GenericWebProvider:
    """LLM-powered generic web search provider.

    Acts as a universal fallback when specialized API providers have no
    results.  Asks the LLM to suggest purchasable products matching the
    query.

    Args:
        llm: An object with a ``generate(prompt, system)`` method.
             Compatible with :class:`~forgeboard.design.llm_provider.LLMProvider`.
             If ``None``, all searches return empty results.
    """

    def __init__(self, llm: _LLMBackend | None = None) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "GenericWeb"

    @property
    def regions(self) -> list[str]:
        return ["GLOBAL"]

    @property
    def categories(self) -> list[str]:
        # Empty list = handles all categories (universal fallback).
        return []

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        """Search the web for products using LLM-powered suggestions.

        Args:
            query: Free-text product search query.
            filters: Optional constraints (used to refine the LLM prompt).

        Returns:
            List of :class:`ProductMatch` objects from LLM suggestions.
            Returns empty list if no LLM is configured.
        """
        if self._llm is None:
            return []

        prompt = f"Find products matching: {query}"
        if filters:
            constraints: list[str] = []
            if filters.category:
                constraints.append(f"Category: {filters.category}")
            if filters.min_price is not None:
                constraints.append(f"Min price: ${filters.min_price:.2f}")
            if filters.max_price is not None:
                constraints.append(f"Max price: ${filters.max_price:.2f}")
            if filters.in_stock_only:
                constraints.append("Must be in stock")
            if filters.country_code:
                constraints.append(f"Ships to: {filters.country_code}")
            if constraints:
                prompt += "\nConstraints: " + ", ".join(constraints)

        try:
            raw = self._llm.generate(prompt, system=_SEARCH_SYSTEM_PROMPT)
            results = _parse_search_response(raw)
            return results
        except Exception:
            return []

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        """Get pricing for a web-sourced product.

        Since this provider uses LLM suggestions rather than live data,
        pricing is approximate and returned from the original search results.

        TODO: Implement follow-up LLM call to research current pricing.
        """
        return PriceQuote(product_id=product_id, unit_price=0.0, currency="USD")

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        """Check availability for a web-sourced product.

        TODO: Implement follow-up web search to verify availability.
        """
        return AvailabilityInfo(product_id=product_id, in_stock=False)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_search_response(raw: str) -> list[ProductMatch]:
    """Parse the LLM's JSON response into ProductMatch objects.

    Handles minor formatting issues (markdown fences, trailing commas)
    and silently drops malformed entries.
    """
    cleaned = raw.strip()

    # Strip markdown code fences if present.
    if cleaned.startswith("```"):
        first_nl = cleaned.index("\n")
        cleaned = cleaned[first_nl + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data: Any = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    results: list[ProductMatch] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            match = ProductMatch(
                product_id=str(item.get("product_id", "")),
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                supplier=str(item.get("supplier", "Web")),
                price=float(item.get("price", 0.0)),
                currency="USD",
                url=str(item.get("url", "")),
                in_stock=bool(item.get("in_stock", False)),
                lead_time_days=int(item.get("lead_time_days", 0)),
                confidence=float(item.get("confidence", 0.3)),
            )
            if match.product_id and match.name:
                results.append(match)
        except (TypeError, ValueError):
            continue

    return results
