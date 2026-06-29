"""Event-bus contracts (transport-agnostic)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DomainEvent:
    """Immutable event emitted by a bounded context."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str | None = None


EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventBus(ABC):
    """Publish/subscribe interface. Implementations may be in-process or broker-backed."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...

    @abstractmethod
    def subscribe(self, event_name: str, handler: EventHandler) -> None: ...
