"""COTS component search and procurement integration.

This package provides a location-aware, provider-extensible architecture
for sourcing commercial off-the-shelf (COTS) components.  The key
principle: **search LOCAL first, then expand outward**.

Public API:

- :class:`SupplierProvider` -- protocol for supplier backends.
- :class:`ProviderRegistry` -- location-aware provider management.
- :class:`COTSResearcher` -- buy-vs-build decision engine.
- Data types: :class:`SearchFilters`, :class:`ProductMatch`,
  :class:`PriceQuote`, :class:`AvailabilityInfo`, :class:`BuyBuildDecision`,
  :class:`ComparisonReport`.
"""

from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
    SupplierProvider,
)
from forgeboard.procure.registry import ProviderRegistry
from forgeboard.procure.researcher import (
    BuyBuildDecision,
    COTSResearcher,
    ComparisonReport,
    Decision,
)

__all__ = [
    "AvailabilityInfo",
    "BuyBuildDecision",
    "COTSResearcher",
    "ComparisonReport",
    "Decision",
    "PriceQuote",
    "ProductMatch",
    "ProviderRegistry",
    "SearchFilters",
    "SupplierProvider",
]
