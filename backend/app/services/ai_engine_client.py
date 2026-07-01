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

    async def frame(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        organization_id: str,
        branch_id: str,
        camera_id: str | None = None,
        recognize_face: bool = False,
        min_confidence: float = 0.4,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/ai/frame"
        files = {"image": (filename, content, content_type)}
        data: dict[str, str] = {
            "organization_id": organization_id,
            "branch_id": branch_id,
            "recognize_face": "true" if recognize_face else "false",
            "min_confidence": str(min_confidence),
        }
        if camera_id:
            data["camera_id"] = camera_id
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, files=files, data=data)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine frame failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def capture(
        self,
        *,
        stream_url: str,
        model: str | None = None,
        open_timeout_ms: int = 5000,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/capture"
        payload = {
            "stream_url": stream_url,
            "open_timeout_ms": open_timeout_ms,
        }
        if model:
            payload["model"] = model
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine capture failed: %s", exc)
            raise AIEngineError(str(exc)) from exc
