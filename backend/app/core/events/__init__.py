"""Event bus package.

Split into:
    base        -- abstract `DomainEvent`, `EventBus`, `EventHandler` types.
    in_memory   -- single-process `InMemoryEventBus` used by the modular monolith.

A broker-backed implementation (Redis Streams, NATS, Kafka, ...) can be plugged
in later by providing another `EventBus` and registering it via the DI layer.
"""

from app.core.events.base import DomainEvent, EventBus, EventHandler
from app.core.events.in_memory import InMemoryEventBus

__all__ = ["DomainEvent", "EventBus", "EventHandler", "InMemoryEventBus"]
