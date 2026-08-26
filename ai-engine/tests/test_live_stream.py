from __future__ import annotations

import time

import numpy as np
import pytest

from app.api import live


class _Request:
    async def is_disconnected(self) -> bool:
        return False


class _Capture:
    def __init__(self):
        self.frame = np.full((90, 160, 3), 120, dtype=np.uint8)

    def isOpened(self) -> bool:
        return True

    def read(self):
        return True, self.frame.copy()

    def set(self, *_args):
        return True

    def release(self) -> None:
        return None


class _SlowDetector:
    model_name = "slow-test-model"

    def detect_dense_bgr(self, *_args):
        time.sleep(0.35)
        return []


@pytest.mark.asyncio
async def test_slow_inference_does_not_block_mjpeg_frames(monkeypatch):
    detector = _SlowDetector()
    monkeypatch.setattr(live, "_open_capture", lambda *_args: _Capture())
    monkeypatch.setattr(
        live.YoloDetector, "get", staticmethod(lambda: detector)
    )
    monkeypatch.setattr(live, "_label_from_training", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(live, "_label_with_sku", lambda *_args, **_kwargs: None)

    stream = live._mjpeg_frames(
        _Request(),
        "rtsp://test",
        30.0,
        1_000,
        70,
        True,
        1,
    )
    started = time.perf_counter()
    try:
        chunks = [await anext(stream) for _ in range(4)]
    finally:
        await stream.aclose()

    assert all(chunk.startswith(b"--frame") for chunk in chunks)
    # Four 30-fps frames should arrive in about 0.13s. The old inline design
    # waited 0.35s for YOLO before every frame and took over 1.4s.
    assert time.perf_counter() - started < 0.30
