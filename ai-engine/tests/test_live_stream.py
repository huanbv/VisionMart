from __future__ import annotations

import time

import numpy as np
import pytest

from app.api import live
from app.services import person_tracker


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


def test_cached_product_boxes_scale_to_live_resolution(monkeypatch):
    monkeypatch.setattr(person_tracker, "_LATEST_PRODUCT_BOXES", {})
    product = person_tracker.TrackedObject(
        track_id=7,
        class_name="du_sti",
        confidence=0.82,
        x1=100,
        y1=50,
        x2=200,
        y2=150,
    )
    person_tracker._cache_latest_product_boxes(
        "camera-1", [product], frame_w=400, frame_h=200
    )

    boxes = person_tracker.get_latest_product_boxes(
        "camera-1", frame_w=800, frame_h=400
    )

    assert boxes[0]["bbox"] == {
        "x1": 200,
        "y1": 100,
        "x2": 400,
        "y2": 300,
    }


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
        use_cached_detections=False,
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


@pytest.mark.asyncio
async def test_cached_overlay_never_loads_second_yolo(monkeypatch):
    monkeypatch.setattr(live, "_open_capture", lambda *_args: _Capture())

    def fail_if_loaded():
        raise AssertionError("live view must reuse /ai/frame detections")

    monkeypatch.setattr(live.YoloDetector, "get", staticmethod(fail_if_loaded))
    stream = live._mjpeg_frames(
        _Request(),
        "rtsp://test",
        30.0,
        1_000,
        70,
        True,
        1,
        camera_key="camera-1",
        use_cached_detections=True,
    )
    try:
        chunk = await anext(stream)
    finally:
        await stream.aclose()

    assert chunk.startswith(b"--frame")
