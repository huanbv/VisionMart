from __future__ import annotations

import base64

import numpy as np

from app.vision.storage.step_writer import DebugCollector


def test_encode_inline_returns_jpeg_steps_in_canonical_order():
    collector = DebugCollector("cam-lab", enabled=True)
    original = np.full((40, 60, 3), 10, dtype=np.uint8)
    boxed = np.full((40, 60, 3), 80, dtype=np.uint8)
    collector.add("result", boxed, products=1)
    collector.add("original", original, bytes=120)

    steps = collector.encode_inline(quality=70, max_edge=64)
    assert [s["step"] for s in steps] == ["original", "result"]
    assert steps[0]["label"] == "Ảnh gốc"
    assert steps[1]["label"] == "Kết quả gán SKU"
    for step in steps:
        raw = base64.b64decode(step["image_jpeg_b64"])
        assert raw[:2] == b"\xff\xd8"
        assert step["elapsed_ms"] is not None


def test_encode_inline_is_noop_when_collector_disabled():
    collector = DebugCollector("cam-lab", enabled=False)
    collector.add("original", np.zeros((8, 8, 3), dtype=np.uint8))
    assert collector.encode_inline() == []
