"""Mouser Electronics supplier provider (stub).

Placeholder implementation for future Mouser API integration.
Mouser serves the US, EU, and global markets with a broad electronics
catalog similar to Digi-Key.

TODO: Integrate with Mouser Search API v2.
TODO: Implement API key authentication.
TODO: Add parametric search support.
TODO: Handle regional pricing (Mouser has region-specific sites).
"""

from __future__ import annotations

from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
)


class MouserProvider:
    """Mouser Electronics distributor provider.

    Stub implementation -- all search methods return empty results.
    Designed for the Mouser Search API which provides keyword-based
    product lookup with real-time pricing and inventory.

    Args:
        api_key: Mouser API key. Not used in the stub.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "Mouser"

    @property
    def regions(self) -> list[str]:
        return ["US", "EU", "GLOBAL"]

    @property
    def categories(self) -> list[str]:
        return ["electronics", "semiconductors", "connectors", "sensors"]

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        """Search Mouser product catalog.

        TODO: Implement Mouser keyword search API call.
        TODO: Map SearchFilters to Mouser's filter parameters.
        """
        return []

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        """Get Mouser pricing with quantity breaks.

        TODO: Implement Mouser pricing API call.
        TODO: Parse price break tiers.
        """
        return PriceQuote(product_id=product_id, unit_price=0.0, currency="USD")

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        """Check Mouser real-time inventory.

        TODO: Implement Mouser inventory API call.
        """
        return AvailabilityInfo(product_id=product_id, in_stock=False)
