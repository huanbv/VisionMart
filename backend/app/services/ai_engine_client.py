"""HTTP client for the AI Engine service.

Thin wrapper around httpx targeting ``AI_ENGINE_BASE_URL``. Keeps the
backend's domain code unaware of transport details.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class AIEngineError(RuntimeError):
    """Raised when the AI Engine is unreachable or returns an error."""


class AIEngineClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self._base_url = (base_url or get_settings().AI_ENGINE_BASE_URL).rstrip("/")
        self._timeout = timeout

    async def detect(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/detect"
        files = {"image": (filename, content, content_type)}
        params = {"model": model} if model else None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, files=files, params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine detect failed: %s", exc)
            raise AIEngineError(str(exc)) from exc
