"""HTTP client for the AI Engine service.

Thin wrapper around httpx targeting ``AI_ENGINE_BASE_URL``. Keeps the
backend's domain code unaware of transport details.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class AIEngineError(RuntimeError):
    """Raised when the AI Engine is unreachable or returns an error."""


class AIEngineNotFoundError(AIEngineError):
    """Raised when the AI Engine reports 404 for the requested resource."""


class AIEngineClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self._base_url = (base_url or get_settings().AI_ENGINE_BASE_URL).rstrip("/")
        self._timeout = timeout
        # AI Engine endpoints require this shared secret (see
        # ai-engine/app/security.py) so an attacker who can reach the
        # service can't trigger inference/training/capture for free.
        self._headers = {"X-AI-Engine-Key": get_settings().AI_ENGINE_API_KEY}

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
                resp = await client.post(
                    url, files=files, params=params, headers=self._headers
                )
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
                resp = await client.post(
                    url, files=files, data=data, headers=self._headers
                )
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
                resp = await client.post(url, json=payload, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine capture failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def live_stream(
        self,
        *,
        stream_url: str,
        fps: float = 8.0,
        open_timeout_ms: int = 5000,
    ) -> AsyncIterator[bytes]:
        """Async-generator proxy for the ai-engine's continuous MJPEG
        ``/live`` endpoint (app/api/live.py). Yields raw multipart chunk
        bytes as they arrive and forwards them as-is -- the backend never
        buffers a whole frame here, so a slow browser tab doesn't pile up
        server-side memory. ``timeout=None`` because this connection is
        meant to stay open for as long as someone is watching, not the
        short request timeout every other method here uses.
        """
        url = f"{self._base_url}/live"
        params = {
            "stream_url": stream_url,
            "fps": fps,
            "open_timeout_ms": open_timeout_ms,
        }
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", url, params=params, headers=self._headers
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except httpx.HTTPError as exc:
            logger.warning("ai-engine live stream failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def start_training(
        self,
        *,
        job_id: str,
        organization_id: str,
        branch_id: str | None,
        class_map: dict[str, list[str]],
        class_to_sku: dict[str, str],
        epochs: int,
        image_size: int,
    ) -> dict[str, Any]:
        """Trigger a training run on the ai-engine.

        ``class_map`` maps YOLO class name -> list of MinIO storage keys.
        """
        url = f"{self._base_url}/ai/train"
        payload: dict[str, Any] = {
            "job_id": job_id,
            "organization_id": organization_id,
            "branch_id": branch_id,
            "class_map": class_map,
            "class_to_sku": class_to_sku,
            "epochs": epochs,
            "image_size": image_size,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine train start failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def training_status(self, job_id: str) -> dict[str, Any]:
        url = f"{self._base_url}/ai/train/{job_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=self._headers)
                if resp.status_code == 404:
                    raise AIEngineNotFoundError(f"job {job_id} not found")
                resp.raise_for_status()
                return resp.json()
        except AIEngineNotFoundError:
            raise
        except httpx.HTTPError as exc:
            logger.warning("ai-engine train status failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def deploy_weight(
        self,
        *,
        weight_key: str,
        organization_id: str,
        branch_id: str | None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/ai/config/model"
        payload: dict[str, Any] = {
            "weight_key": weight_key,
            "organization_id": organization_id,
            "branch_id": branch_id,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine deploy weight failed: %s", exc)
            raise AIEngineError(str(exc)) from exc
