"""Simple publish-subscribe event bus for ForgeBoard pipeline events.

Provides decoupled communication between pipeline stages: when the cascade
engine updates a component, it publishes an event; listeners (BOM generator,
validation pipeline, UI) react without tight coupling.

All handlers are called synchronously in registration order.  This keeps the
system deterministic and easy to reason about during cascade propagation.

Example::

    bus = EventBus()
    bus.subscribe(COMPONENT_UPDATED, lambda data: print(data))
    bus.publish(COMPONENT_UPDATED, {"component_id": "BRKT-001", "field": "mass_g"})
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pre-defined event type constants
# ---------------------------------------------------------------------------

COMPONENT_CREATED: str = "component.created"
COMPONENT_UPDATED: str = "component.updated"
COMPONENT_DELETED: str = "component.deleted"
ASSEMBLY_UPDATED: str = "assembly.updated"
BOM_UPDATED: str = "bom.updated"
VALIDATION_FAILED: str = "validation.failed"
COLLISION_DETECTED: str = "collision.detected"
COST_CHANGED: str = "cost.changed"
MASS_CHANGED: str = "mass.changed"

# Collect all event types for programmatic access
ALL_EVENT_TYPES: list[str] = [
    COMPONENT_CREATED,
    COMPONENT_UPDATED,
    COMPONENT_DELETED,
    ASSEMBLY_UPDATED,
    BOM_UPDATED,
    VALIDATION_FAILED,
    COLLISION_DETECTED,
    COST_CHANGED,
    MASS_CHANGED,
]


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """Simple publish-subscribe event bus for ForgeBoard pipeline events.

    Handlers are invoked synchronously in the order they were registered.
    This guarantees deterministic execution order during cascade propagation.

    Usage::

        bus = EventBus()

        def on_update(data: dict) -> None:
            print(f"Component updated: {data}")

        bus.subscribe("component.updated", on_update)
        bus.publish("component.updated", {"component_id": "BRKT-001"})
        bus.unsubscribe("component.updated", on_update)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = (
            defaultdict(list)
        )

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        """Register *handler* to be called when *event_type* is published.

        The same handler can be registered for multiple event types.
        Registering the same handler twice for the same event type results
        in it being called twice (no deduplication).
        """
        self._handlers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        """Remove *handler* from *event_type*.

        If the handler was registered multiple times, only the first
        occurrence is removed.  Silently does nothing if the handler is
        not found.
        """
        handlers = self._handlers.get(event_type)
        if handlers is None:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Invoke all handlers registered for *event_type* with *data*.

        Handlers are called synchronously in registration order.  If a
        handler raises an exception it is logged and the remaining handlers
        still execute.
        """
        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        for handler in list(handlers):  # copy to allow mutation during iteration
            try:
                handler(data)
            except Exception:
                logger.exception(
                    "Handler %r raised an exception for event %r",
                    handler,
                    event_type,
                )

    def clear(self, event_type: str | None = None) -> None:
        """Remove all handlers for *event_type*, or all handlers if None."""
        if event_type is None:
            self._handlers.clear()
        else:
            self._handlers.pop(event_type, None)

    @property
    def handler_count(self) -> int:
        """Total number of handler registrations across all event types."""
        return sum(len(hs) for hs in self._handlers.values())

    def __repr__(self) -> str:
        types = len(self._handlers)
        total = self.handler_count
        return f"EventBus({types} event types, {total} handlers)"
