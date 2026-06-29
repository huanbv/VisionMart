"""Central FastAPI dependency providers.

Concrete repository and service providers will be added per-module. The
container exposes singletons for cross-cutting infrastructure (event bus,
settings, ...).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.core.events import EventBus, InMemoryEventBus
from app.database.session import get_session


@lru_cache(maxsize=1)
def get_event_bus() -> EventBus:
    """Process-wide singleton event bus.

    Swap implementation here (e.g. Redis Streams) without touching call sites.
    """
    return InMemoryEventBus()


# Reusable Annotated aliases keep route signatures short.
SettingsDep = Annotated[Settings, Depends(get_settings)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
