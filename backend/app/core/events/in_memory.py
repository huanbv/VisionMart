"""Process-local event bus. Replace with a broker-backed implementation later."""

from __future__ import annotations

import asyncio
import logging

from app.core.events.base import DomainEvent, EventBus, EventHandler

logger = logging.getLogger(__name__)


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_name, []).append(handler)

    async def publish(self, event: DomainEvent) -> None:
        handlers = self._handlers.get(event.name, [])
        if not handlers:
            return
        # Handlers are isolated: a failing one must not block the others.
        results = await asyncio.gather(
            *(handler(event) for handler in handlers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.exception("Event handler failed for %s", event.name, exc_info=result)
