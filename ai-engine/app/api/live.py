"""Continuous MJPEG live-view stream for a camera's stream_url.

Unlike `/capture` (opens a fresh `cv2.VideoCapture`, reads exactly one
frame, closes) this endpoint keeps a single `cv2.VideoCapture` open for
the lifetime of the HTTP connection and continuously pushes frames as a
`multipart/x-mixed-replace` stream — the same MJPEG format IP cameras
themselves often serve natively, and something every browser already
knows how to decode frame-by-frame. See docs/21_CAMERA_MANAGER.md
("Real-time Streaming Design") for where this fits in the wider design;
this is the pragmatic MJPEG implementation of that section rather than
the WebRTC/HLS path also described there.

The backend proxies this endpoint (see camera_router.py's
`/cameras/{id}/live`) rather than exposing it to the browser directly —
same "AI Engine isolation" boundary every other route here respects.
"""

from __future__ import annotations

import asyncio
import logging

import cv2  # type: ignore[import-not-found]
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.security import require_api_key

logger = logging.getLogger("ai-engine.live")

router = APIRouter(tags=["live"], dependencies=[Depends(require_api_key)])

_BOUNDARY = b"frame"
_MIN_FPS = 1.0
_MAX_FPS = 15.0
_MAX_CONSECUTIVE_FAILURES = 10


def _open_capture(stream_url: str, open_timeout_ms: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_ms)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, open_timeout_ms)
    except Exception:  # pragma: no cover — older OpenCV builds
        pass
    return cap


async def _mjpeg_frames(
    request: Request,
    stream_url: str,
    fps: float,
    open_timeout_ms: int,
    jpeg_quality: int,
):
    fps = max(_MIN_FPS, min(_MAX_FPS, fps))
    interval = 1.0 / fps

    cap = await asyncio.to_thread(_open_capture, stream_url, open_timeout_ms)
    try:
        if not cap.isOpened():
            logger.warning("live stream: could not open %s", stream_url)
            return

        consecutive_failures = 0
        while True:
            # Stop as soon as the client (backend proxy -> browser tab)
            # goes away instead of reading an RTSP/video source forever
            # with nobody watching.
            if await request.is_disconnected():
                break

            ok, frame = await asyncio.to_thread(cap.read)
            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.warning(
                        "live stream: %d consecutive read failures, stopping %s",
                        consecutive_failures,
                        stream_url,
                    )
                    break
                await asyncio.sleep(interval)
                continue
            consecutive_failures = 0

            ok2, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            )
            if not ok2:
                await asyncio.sleep(interval)
                continue

            chunk = buf.tobytes()
            yield (
                b"--" + _BOUNDARY + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(chunk)).encode("ascii") + b"\r\n\r\n"
                + chunk + b"\r\n"
            )
            await asyncio.sleep(interval)
    finally:
        await asyncio.to_thread(cap.release)


@router.get("/live")
async def live_stream(
    request: Request,
    stream_url: str = Query(..., min_length=1, max_length=1024),
    fps: float = Query(default=8.0, ge=_MIN_FPS, le=_MAX_FPS),
    open_timeout_ms: int = Query(default=5000, ge=500, le=30000),
    jpeg_quality: int = Query(default=70, ge=10, le=95),
) -> StreamingResponse:
    return StreamingResponse(
        _mjpeg_frames(request, stream_url, fps, open_timeout_ms, jpeg_quality),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY.decode()}",
    )
