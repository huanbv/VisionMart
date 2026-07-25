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

    async def get_vision_config(self) -> dict[str, Any]:
        """Current OpenCV preprocessing settings (effective + overrides)."""
        url = f"{self._base_url}/ai/vision-config"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine get vision-config failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def update_vision_config(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Persist runtime overrides so the operator doesn't have to edit
        ``.env`` and restart. A null value clears that override."""
        url = f"{self._base_url}/ai/vision-config"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.put(
                    url, json={"settings": settings}, headers=self._headers
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            # 400 carries the "unknown setting" message — surface it as-is
            # so the operator sees which key was wrong.
            raise AIEngineError(exc.response.text) from exc
        except httpx.HTTPError as exc:
            logger.warning("ai-engine update vision-config failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def reset_vision_config(self) -> dict[str, Any]:
        url = f"{self._base_url}/ai/vision-config"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.delete(url, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("ai-engine reset vision-config failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def trace_frame(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        camera_key: str = "default",
    ) -> dict[str, Any]:
        """Run the OpenCV preprocessing chain with per-stage tracing on.

        Unlike :meth:`frame`, this deliberately skips detection — it exists
        to answer "what did each preprocessing step do to this frame?" for
        the admin pipeline view, so it stays cheap enough to call
        interactively.
        """
        url = f"{self._base_url}/ai/trace/frame"
        files = {"file": (filename, content, content_type)}
        data = {"camera_key": camera_key}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    url, files=files, data=data, headers=self._headers
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            # 409 = tracing switched off on the engine; surface that
            # verbatim so the operator sees the actionable message rather
            # than a generic failure.
            detail = exc.response.text
            logger.warning("ai-engine trace failed (%s): %s", exc.response.status_code, detail)
            raise AIEngineError(detail) from exc
        except httpx.HTTPError as exc:
            logger.warning("ai-engine trace failed: %s", exc)
            raise AIEngineError(str(exc)) from exc

    async def trace_image(
        self, *, trace_id: str, stage_file: str, camera_key: str = "default"
    ) -> tuple[bytes, str]:
        """Fetch one stored stage image. Returns ``(content, media_type)``."""
        url = f"{self._base_url}/ai/trace/{trace_id}/{stage_file}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    url, params={"camera_key": camera_key}, headers=self._headers
                )
                if resp.status_code == 404:
                    raise AIEngineNotFoundError("Trace image not found.")
                resp.raise_for_status()
                return resp.content, resp.headers.get("content-type", "image/jpeg")
        except AIEngineNotFoundError:
            raise
        except httpx.HTTPError as exc:
            logger.warning("ai-engine trace image failed: %s", exc)
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
        detect: bool = True,
        detect_every_n: int = 3,
        roi_zones: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Async-generator proxy for the ai-engine's continuous MJPEG
        ``/live`` endpoint (app/api/live.py). Yields raw multipart chunk
        bytes as they arrive and forwards them as-is -- the backend never
        buffers a whole frame here, so a slow browser tab doesn't pile up
        server-side memory. ``timeout=None`` because this connection is
        meant to stay open for as long as someone is watching, not the
        short request timeout every other method here uses.

        ``detect``/``detect_every_n`` are forwarded as-is to ai-engine,
        which burns YOLO boxes + a small HUD directly into the frames
        when enabled (see live.py) -- the backend never touches pixels
        here, it's a pure byte pass-through either way.
        """
        url = f"{self._base_url}/live"
        params = {
            "stream_url": stream_url,
            "fps": fps,
            "open_timeout_ms": open_timeout_ms,
            "detect": "true" if detect else "false",
            "detect_every_n": detect_every_n,
        }
        # Chuyển vùng ROI xuống để ai-engine chỉ vẽ box trong vùng (khớp giỏ).
        if roi_zones:
            params["roi_zones"] = roi_zones
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", url, params=params, headers=self._headers
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except httpx.RemoteProtocolError as exc:
            # Trình duyệt đóng luồng giữa chừng (đổi camera / đóng panel /
            # rời trang) => ai-engine ngắt kết nối, httpx báo "peer closed
            # connection". Đây là kết thúc BÌNH THƯỜNG của một luồng live,
            # không phải sự cố: dừng im lặng thay vì ném traceback lên ASGI.
            logger.debug("ai-engine live stream closed by client: %s", exc)
            return
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
