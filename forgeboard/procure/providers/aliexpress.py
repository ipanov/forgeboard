"""AliExpress supplier provider (stub).

Placeholder implementation for future AliExpress API integration.
AliExpress is treated as a GLOBAL provider and serves as a low-cost
fallback for general components, electronics, mechanical parts, and
fasteners.

TODO: Integrate with AliExpress Affiliate/Open Platform API.
TODO: Implement product search, pricing, and availability endpoints.
TODO: Add currency conversion (CNY -> user currency).
TODO: Handle shipping time estimation for different countries.
"""

from __future__ import annotations

from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
)


class AliExpressProvider:
    """AliExpress marketplace provider.

    Stub implementation -- all search methods return empty results.
    Register this provider to reserve the slot in the registry so that
    future API integration only requires filling in the method bodies.
    """

    @property
    def name(self) -> str:
        return "AliExpress"

    @property
    def regions(self) -> list[str]:
        return ["GLOBAL"]

    @property
    def categories(self) -> list[str]:
        return ["general", "electronics", "mechanical", "fasteners"]

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        """Search AliExpress for products.

        TODO: Implement AliExpress API search integration.
        """
        return []

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        """Get pricing from AliExpress.

        TODO: Implement AliExpress pricing API call.
        """
        return PriceQuote(product_id=product_id, unit_price=0.0, currency="USD")

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        """Check AliExpress stock availability.

        TODO: Implement AliExpress availability API call.
        """
        return AvailabilityInfo(product_id=product_id, in_stock=False)
