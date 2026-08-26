from __future__ import annotations

import importlib
from types import SimpleNamespace

import numpy as np
import pytest

capture_api = importlib.import_module("app.api.capture")


@pytest.mark.asyncio
async def test_capture_only_skips_detector(monkeypatch):
    frame = np.full((48, 64, 3), 127, dtype=np.uint8)
    outcome = SimpleNamespace(
        success=True,
        frame=frame,
        error=None,
        capture_ms=3.0,
        fps=1.0,
        dropped_count=0,
    )
    monkeypatch.setattr(capture_api, "instrumented_capture", lambda *args: outcome)
    monkeypatch.setattr(
        capture_api,
        "resolve_detection_weight",
        lambda: "/models/checkout.pt",
    )

    class DetectorMustNotRun:
        @classmethod
        def get(cls):
            raise AssertionError("capture-only mode must not load YOLO")

    monkeypatch.setattr(capture_api, "YoloDetector", DetectorMustNotRun)

    result = await capture_api.capture(
        capture_api.CaptureRequest(stream_url="rtsp://camera", detect=False)
    )

    assert result["detections"] == []
    assert result["model"] == "/models/checkout.pt"
    assert result["image"]["width"] == 64
    assert result["image"]["height"] == 48
    assert result["frame_base64"]
