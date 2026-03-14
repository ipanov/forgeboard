"""Location-aware supplier provider registry.

The :class:`ProviderRegistry` manages a collection of
:class:`~forgeboard.procure.provider.SupplierProvider` instances and orders
them by geographic proximity to the user.  The guiding principle is
**search LOCAL first, then expand outward**:

1. Providers that serve the user's own country.
2. Providers in the same regional grouping (e.g. Balkans, EU, North America).
3. Global / worldwide providers (AliExpress, Temu, etc.).

Adding a new provider is a two-step process:

1. Implement :class:`~forgeboard.procure.provider.SupplierProvider`.
2. Call :meth:`ProviderRegistry.register`.
"""

from __future__ import annotations

from forgeboard.procure.provider import (
    AvailabilityInfo,
    PriceQuote,
    ProductMatch,
    SearchFilters,
    SupplierProvider,
)


# ---------------------------------------------------------------------------
# Region groupings
# ---------------------------------------------------------------------------

# Hard-coded regional affinity groups.  Countries within the same group are
# considered "neighbors" for proximity ordering.

REGION_GROUPS: dict[str, set[str]] = {
    "BALKANS": {"MK", "RS", "BG", "GR", "AL", "XK", "HR", "BA", "ME", "SI"},
    "EU": {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
        "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    },
    "NORTH_AMERICA": {"US", "CA", "MX"},
    "EAST_ASIA": {"CN", "JP", "KR", "TW", "HK"},
    "SOUTHEAST_ASIA": {"SG", "MY", "TH", "VN", "PH", "ID"},
    "OCEANIA": {"AU", "NZ"},
    "UK": {"GB"},
    "MIDDLE_EAST": {"AE", "SA", "IL", "TR"},
}


def _groups_for_country(country: str) -> list[str]:
    """Return all region group names that contain *country*."""
    upper = country.upper()
    return [name for name, members in REGION_GROUPS.items() if upper in members]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ProviderRegistry:
    """Manages supplier providers with location-aware priority ordering.

    Providers are stored in registration order and re-sorted at query time
    based on the user's country code.

    Args:
        user_country: ISO 3166-1 alpha-2 code for the user's location.
                      Defaults to ``'US'``.
    """

    def __init__(self, user_country: str = "US") -> None:
        self.user_country: str = user_country.upper()
        self._providers: list[SupplierProvider] = []

    # -- Registration --------------------------------------------------------

    def register(self, provider: SupplierProvider) -> None:
        """Register a supplier provider.

        Duplicate registrations (same ``provider.name``) are silently ignored.

        Args:
            provider: An object satisfying the :class:`SupplierProvider`
                      protocol.
        """
        existing_names = {p.name for p in self._providers}
        if provider.name not in existing_names:
            self._providers.append(provider)

    # -- Query ---------------------------------------------------------------

    def get_providers(
        self, category: str | None = None
    ) -> list[SupplierProvider]:
        """Get providers ordered by proximity: local -> regional -> global.

        Args:
            category: If provided, only return providers that list this
                      category (or have an empty categories list, meaning
                      they handle everything).

        Returns:
            Providers sorted so that local ones appear first.
        """
        candidates = self._providers
        if category:
            cat_lower = category.lower()
            candidates = [
                p
                for p in candidates
                if not p.categories
                or cat_lower in [c.lower() for c in p.categories]
            ]

        user_groups = _groups_for_country(self.user_country)

        def _sort_key(provider: SupplierProvider) -> tuple[int, str]:
            """Return (priority_tier, name) for sorting.

            Tier 0 = serves user's exact country
            Tier 1 = serves user's region group or lists "EU" matching EU group
            Tier 2 = global provider
            Tier 3 = everything else (different region)
            """
            regions_upper = [r.upper() for r in provider.regions]

            # Tier 0: exact country match
            if self.user_country in regions_upper:
                return (0, provider.name)

            # Check if provider lists a group name that matches user's groups.
            # e.g. provider regions=["EU"] and user is in EU group.
            for region in regions_upper:
                if region in user_groups:
                    return (1, provider.name)

            # Check if any provider region is in the same group as the user.
            for region in regions_upper:
                provider_groups = _groups_for_country(region)
                if any(g in user_groups for g in provider_groups):
                    return (1, provider.name)

            # Tier 2: global
            if "GLOBAL" in regions_upper:
                return (2, provider.name)

            # Tier 3: unrelated region
            return (3, provider.name)

        return sorted(candidates, key=_sort_key)

    def search_all(
        self,
        query: str,
        category: str | None = None,
        filters: SearchFilters | None = None,
    ) -> list[ProductMatch]:
        """Search across all relevant providers, ordered by location priority.

        Results from local providers appear before results from global ones.
        Within each provider's result set, the original relevance ordering is
        preserved.

        Args:
            query: Free-text search string.
            category: Optional category to restrict which providers are queried.
            filters: Optional search constraints.

        Returns:
            Aggregated list of :class:`ProductMatch` objects.
        """
        providers = self.get_providers(category=category)
        results: list[ProductMatch] = []
        for provider in providers:
            try:
                matches = provider.search(query, filters=filters)
                results.extend(matches)
            except Exception:
                # Individual provider failures should not break the aggregate
                # search.  In production this would be logged.
                continue
        return results

    def get_price(self, provider_name: str, product_id: str, quantity: int = 1) -> PriceQuote | None:
        """Get pricing from a specific named provider.

        Args:
            provider_name: The ``name`` property of the target provider.
            product_id: Provider-specific product identifier.
            quantity: Desired quantity for volume pricing.

        Returns:
            A :class:`PriceQuote`, or ``None`` if the provider is not found.
        """
        for p in self._providers:
            if p.name == provider_name:
                return p.get_price(product_id, quantity)
        return None

    def check_availability(self, provider_name: str, product_id: str) -> AvailabilityInfo | None:
        """Check availability from a specific named provider.

        Args:
            provider_name: The ``name`` property of the target provider.
            product_id: Provider-specific product identifier.

        Returns:
            An :class:`AvailabilityInfo`, or ``None`` if the provider is not found.
        """
        for p in self._providers:
            if p.name == provider_name:
                return p.check_availability(product_id)
        return None
