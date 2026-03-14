"""McMaster-Carr supplier provider (stub).

Placeholder implementation for future McMaster-Carr integration.
McMaster-Carr is US-only and specializes in mechanical/industrial
components: fasteners, raw materials, bearings, seals, structural
shapes, and tooling.

Note: McMaster-Carr does not offer a public API.  Integration would
require either web scraping (subject to ToS) or a licensed data feed
partnership.

TODO: Investigate McMaster-Carr data feed options.
TODO: Implement product search via catalog number or keyword.
TODO: Add support for McMaster's parametric filtering (thread size,
      material grade, etc.).
"""

from __future__ import annotations

from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
)


class McMasterProvider:
    """McMaster-Carr industrial supply provider.

    Stub implementation -- all search methods return empty results.
    McMaster-Carr is the go-to source for mechanical components in the US.

    Note: McMaster-Carr does not provide a public API.  This stub
    reserves the integration point for when a data access method
    becomes available.
    """

    @property
    def name(self) -> str:
        return "McMaster-Carr"

    @property
    def regions(self) -> list[str]:
        return ["US"]

    @property
    def categories(self) -> list[str]:
        return ["fasteners", "mechanical", "structural", "bearings", "seals"]

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        """Search McMaster-Carr catalog.

        TODO: Implement McMaster-Carr product search.
        TODO: Note that McMaster-Carr has no public API -- integration
              will require an alternative approach.
        """
        return []

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        """Get McMaster-Carr pricing.

        TODO: Implement pricing lookup.
        """
        return PriceQuote(product_id=product_id, unit_price=0.0, currency="USD")

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        """Check McMaster-Carr availability.

        McMaster-Carr ships most items same-day from US warehouses.

        TODO: Implement availability check.
        """
        return AvailabilityInfo(product_id=product_id, in_stock=False)
