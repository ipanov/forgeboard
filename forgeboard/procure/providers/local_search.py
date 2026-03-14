"""Location-aware local supplier search provider.

Uses an LLM to find local suppliers, fabrication shops, and component
stores in the user's country or region.  This is the most interesting
provider in the procurement pipeline -- it bridges the gap between
global online marketplaces and the reality that many hardware projects
need local fabrication (sheet metal shops, 3D printing services,
electronics stores with walk-in availability).

The LLM is prompted with the user's country and the component query,
and asked to suggest local businesses that could supply or fabricate
the needed part.

TODO: Integrate with Google Places API or similar for grounded local
      business search.
TODO: Add caching per (country, query) to avoid repeated LLM calls.
TODO: Support city-level location for better local results.
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
    """Minimal LLM interface needed by LocalSearchProvider."""

    def generate(self, prompt: str, system: str = "") -> str: ...


# ---------------------------------------------------------------------------
# Country name mapping (subset -- extend as needed)
# ---------------------------------------------------------------------------

_COUNTRY_NAMES: dict[str, str] = {
    "US": "United States",
    "CA": "Canada",
    "MX": "Mexico",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "NL": "Netherlands",
    "BE": "Belgium",
    "AT": "Austria",
    "CH": "Switzerland",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
    "FI": "Finland",
    "PL": "Poland",
    "CZ": "Czech Republic",
    "RO": "Romania",
    "HU": "Hungary",
    "BG": "Bulgaria",
    "HR": "Croatia",
    "SI": "Slovenia",
    "RS": "Serbia",
    "MK": "North Macedonia",
    "BA": "Bosnia and Herzegovina",
    "ME": "Montenegro",
    "AL": "Albania",
    "XK": "Kosovo",
    "GR": "Greece",
    "TR": "Turkey",
    "IL": "Israel",
    "AE": "United Arab Emirates",
    "SA": "Saudi Arabia",
    "CN": "China",
    "JP": "Japan",
    "KR": "South Korea",
    "TW": "Taiwan",
    "IN": "India",
    "AU": "Australia",
    "NZ": "New Zealand",
    "SG": "Singapore",
    "MY": "Malaysia",
    "TH": "Thailand",
}


# ---------------------------------------------------------------------------
# System prompt for local supplier search
# ---------------------------------------------------------------------------

_LOCAL_SEARCH_SYSTEM = """\
You are a procurement assistant specializing in finding LOCAL suppliers
and fabrication services. Given a country and a component/service query,
suggest real local businesses that could supply or fabricate the item.

For each suggestion, provide:
- product_id: a unique identifier (use business name + service type)
- name: the business or service name
- description: what they offer relevant to the query
- supplier: the business name
- price: estimated price in USD (your best guess, 0 if unknown)
- url: their website URL if you know it, empty string otherwise
- in_stock: true if they likely have it available
- lead_time_days: typical turnaround time
- confidence: 0.0-1.0 how confident you are this is a real business

Focus on:
- Local electronics component stores
- Sheet metal fabrication shops
- 3D printing / rapid prototyping services
- CNC machining shops
- Industrial supply distributors with local branches

Respond with a JSON array of objects. Return at most 5 results.
If you cannot find relevant local suppliers, return an empty array: []
Do not include markdown fences. Return only valid JSON."""


class LocalSearchProvider:
    """LLM-powered local supplier discovery provider.

    Queries the LLM to find local fabrication shops, component stores,
    and industrial suppliers in the user's country.  Intended to be
    registered with a high priority (local providers are queried first)
    so that users get nearby options before being shown global results.

    Args:
        country_code: ISO 3166-1 alpha-2 code for the target country.
        llm: An object with a ``generate(prompt, system)`` method.
             If ``None``, all searches return empty results.
    """

    def __init__(
        self,
        country_code: str = "US",
        llm: _LLMBackend | None = None,
    ) -> None:
        self._country_code = country_code.upper()
        self._llm = llm

    @property
    def name(self) -> str:
        return f"Local ({self._country_code})"

    @property
    def regions(self) -> list[str]:
        return [self._country_code]

    @property
    def categories(self) -> list[str]:
        # Local search handles all categories -- it can find fabrication
        # shops, electronics stores, and general suppliers.
        return []

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        """Search for local suppliers using LLM-powered discovery.

        Args:
            query: Component or service description.
            filters: Optional constraints (category is used to refine
                     the LLM prompt).

        Returns:
            List of :class:`ProductMatch` representing local suppliers/services.
            Returns empty list if no LLM is configured.
        """
        if self._llm is None:
            return []

        country_name = _COUNTRY_NAMES.get(self._country_code, self._country_code)

        prompt_parts = [
            f"Country: {country_name} ({self._country_code})",
            f"Query: {query}",
        ]
        if filters and filters.category:
            prompt_parts.append(f"Category: {filters.category}")

        prompt = "\n".join(prompt_parts)

        try:
            raw = self._llm.generate(prompt, system=_LOCAL_SEARCH_SYSTEM)
            return _parse_local_results(raw, self._country_code)
        except Exception:
            return []

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        """Get pricing for a locally-sourced product/service.

        Local pricing typically requires a quote request.  This returns
        a placeholder.

        TODO: Implement quote request workflow for local fabricators.
        """
        return PriceQuote(product_id=product_id, unit_price=0.0, currency="USD")

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        """Check availability for a local supplier.

        TODO: Implement availability check via business contact info.
        """
        return AvailabilityInfo(product_id=product_id, in_stock=False)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_local_results(raw: str, country_code: str) -> list[ProductMatch]:
    """Parse the LLM's JSON response into ProductMatch objects.

    Adds the country code context to each result's supplier field for
    disambiguation when results from multiple countries are merged.
    """
    cleaned = raw.strip()

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
            supplier_name = str(item.get("supplier", "Local"))
            match = ProductMatch(
                product_id=str(item.get("product_id", "")),
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                supplier=f"{supplier_name} ({country_code})",
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
