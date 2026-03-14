"""Digi-Key supplier provider (stub).

Placeholder implementation for future Digi-Key API integration.
Digi-Key serves the US, EU, and global markets with a focus on
electronics, semiconductors, connectors, and sensors.

TODO: Integrate with Digi-Key Product Information API v4.
TODO: Implement OAuth2 authentication flow.
TODO: Add parametric search using Digi-Key's filter taxonomy.
TODO: Handle regional pricing and warehouse routing.
"""

from __future__ import annotations

from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
)


class DigiKeyProvider:
    """Digi-Key electronics distributor provider.

    Stub implementation -- all search methods return empty results.
    Designed for the Digi-Key Product Information API v4 which provides
    keyword search, parametric filtering, and real-time pricing/inventory.

    Args:
        api_key: Digi-Key API client ID. Not used in the stub.
        api_secret: Digi-Key API client secret. Not used in the stub.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret

    @property
    def name(self) -> str:
        return "DigiKey"

    @property
    def regions(self) -> list[str]:
        return ["US", "EU", "GLOBAL"]

    @property
    def categories(self) -> list[str]:
        return ["electronics", "semiconductors", "connectors", "sensors"]

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        """Search Digi-Key product catalog.

        TODO: Implement Digi-Key keyword search API call.
        TODO: Map SearchFilters to Digi-Key parametric filters.
        """
        return []

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        """Get Digi-Key pricing with quantity breaks.

        TODO: Implement Digi-Key pricing API call.
        TODO: Parse quantity break tiers from API response.
        """
        return PriceQuote(product_id=product_id, unit_price=0.0, currency="USD")

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        """Check Digi-Key real-time inventory.

        TODO: Implement Digi-Key inventory API call.
        TODO: Report warehouse location and factory lead time.
        """
        return AvailabilityInfo(product_id=product_id, in_stock=False)
