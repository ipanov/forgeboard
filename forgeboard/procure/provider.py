"""Supplier provider abstraction for COTS component procurement.

Defines the :class:`SupplierProvider` protocol that all supplier backends must
implement, plus the shared data types used across the procurement pipeline:

- :class:`SearchFilters` -- query constraints (price range, stock, category).
- :class:`ProductMatch` -- a single search result from a supplier.
- :class:`PriceQuote` -- pricing with quantity breaks.
- :class:`AvailabilityInfo` -- stock and lead-time information.

Adding a new supplier is as simple as implementing :class:`SupplierProvider`
and registering the instance with :class:`~forgeboard.procure.registry.ProviderRegistry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Constraints applied when searching for products.

    Attributes:
        category: Component category filter (e.g. 'electronics', 'fasteners').
        min_price: Minimum unit price in the provider's native currency.
        max_price: Maximum unit price in the provider's native currency.
        in_stock_only: When True, exclude out-of-stock items.
        country_code: ISO 3166-1 alpha-2 country code for shipping destination.
    """

    category: str = ""
    min_price: float | None = None
    max_price: float | None = None
    in_stock_only: bool = False
    country_code: str = ""


@dataclass(frozen=True, slots=True)
class ProductMatch:
    """A single product returned from a supplier search.

    Attributes:
        product_id: Provider-specific unique identifier.
        name: Human-readable product name.
        description: Short product description.
        supplier: Name of the supplier / marketplace.
        price: Unit price.
        currency: ISO 4217 currency code (e.g. 'USD', 'EUR').
        url: Product page URL.
        specs: Key/value pairs of technical specifications.
        in_stock: Whether the item is currently available.
        lead_time_days: Estimated lead time in calendar days.
        confidence: Match confidence score in [0.0, 1.0].
    """

    product_id: str
    name: str
    description: str = ""
    supplier: str = ""
    price: float = 0.0
    currency: str = "USD"
    url: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    in_stock: bool = True
    lead_time_days: int = 0
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """Pricing information for a specific product.

    Attributes:
        product_id: Provider-specific product identifier.
        unit_price: Price per unit at quantity=1.
        currency: ISO 4217 currency code.
        quantity_breaks: List of (quantity, unit_price) tuples for volume discounts.
        shipping_estimate: Estimated shipping cost in the same currency.
    """

    product_id: str
    unit_price: float
    currency: str = "USD"
    quantity_breaks: list[tuple[int, float]] = field(default_factory=list)
    shipping_estimate: float = 0.0


@dataclass(frozen=True, slots=True)
class AvailabilityInfo:
    """Stock and availability details for a product.

    Attributes:
        product_id: Provider-specific product identifier.
        in_stock: Whether the item is currently in stock.
        quantity_available: Number of units available. -1 means unknown.
        lead_time_days: Estimated delivery lead time in calendar days.
        warehouse_location: Nearest warehouse or shipping origin.
    """

    product_id: str
    in_stock: bool = False
    quantity_available: int = -1
    lead_time_days: int = 0
    warehouse_location: str = ""


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SupplierProvider(Protocol):
    """Abstract supplier interface.

    Each provider wraps a specific supplier, marketplace, or search backend.
    Implementations must satisfy this protocol so the
    :class:`~forgeboard.procure.registry.ProviderRegistry` can treat them
    uniformly.

    The three key properties -- *name*, *regions*, *categories* -- drive the
    location-aware ordering logic: local providers are queried first, global
    ones last.
    """

    @property
    def name(self) -> str:
        """Human-readable provider name (e.g. 'DigiKey', 'AliExpress')."""
        ...

    @property
    def regions(self) -> list[str]:
        """ISO country codes this provider serves.

        Use ``'GLOBAL'`` to indicate worldwide availability.
        Examples: ``['US', 'CA']``, ``['EU']``, ``['GLOBAL']``.
        """
        ...

    @property
    def categories(self) -> list[str]:
        """Component categories this provider handles.

        Examples: ``['electronics', 'fasteners', 'motors']``.
        An empty list means the provider handles all categories.
        """
        ...

    def search(
        self, query: str, filters: SearchFilters | None = None
    ) -> list[ProductMatch]:
        """Search for products matching *query*.

        Args:
            query: Free-text search string.
            filters: Optional constraints to narrow results.

        Returns:
            List of matching products, ordered by relevance.
        """
        ...

    def get_price(self, product_id: str, quantity: int = 1) -> PriceQuote:
        """Get pricing for a specific product.

        Args:
            product_id: Provider-specific product identifier.
            quantity: Desired order quantity (affects volume pricing).

        Returns:
            A :class:`PriceQuote` with unit price and quantity breaks.
        """
        ...

    def check_availability(self, product_id: str) -> AvailabilityInfo:
        """Check stock and availability for a product.

        Args:
            product_id: Provider-specific product identifier.

        Returns:
            An :class:`AvailabilityInfo` with stock level and lead time.
        """
        ...
