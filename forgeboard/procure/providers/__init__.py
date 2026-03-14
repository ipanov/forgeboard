"""Concrete supplier provider implementations.

Each module in this package implements the
:class:`~forgeboard.procure.provider.SupplierProvider` protocol for a
specific supplier or marketplace.  Stub providers (DigiKey, Mouser,
McMaster-Carr, AliExpress) are included as scaffolding for future API
integration.  The :class:`~.generic_web.GenericWebProvider` and
:class:`~.local_search.LocalSearchProvider` use LLM-powered search as
universal fallbacks.
"""

from forgeboard.procure.providers.aliexpress import AliExpressProvider
from forgeboard.procure.providers.digikey import DigiKeyProvider
from forgeboard.procure.providers.generic_web import GenericWebProvider
from forgeboard.procure.providers.local_search import LocalSearchProvider
from forgeboard.procure.providers.mcmaster import McMasterProvider
from forgeboard.procure.providers.mouser import MouserProvider

__all__ = [
    "AliExpressProvider",
    "DigiKeyProvider",
    "GenericWebProvider",
    "LocalSearchProvider",
    "McMasterProvider",
    "MouserProvider",
]
