from __future__ import annotations

import numpy as np

from app.vision.overlay.presence import OVERLAY_MIN_CONFIDENCE, filter_overlay_ghosts


def _wood(h=240, w=320):
    """Uniform counter — no product blobs."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = (42, 88, 145)  # BGR wood-ish
    return frame


def _wood_with_bottle(h=240, w=320):
    frame = _wood(h, w)
    # Saturated red bottle-like patch, different from wood.
    frame[70:170, 120:170] = (40, 40, 220)
    return frame


def _det(x1, y1, x2, y2, conf=0.8, cls="du_sti"):
    return {
        "class_name": cls,
        "confidence": conf,
        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
    }


def test_empty_wood_drops_all_product_ghosts():
    frame = _wood()
    ghosts = [
        _det(10, 10, 80, 80, conf=0.87),
        _det(90, 20, 160, 90, conf=0.78),
        _det(20, 100, 90, 180, conf=0.27),
    ]
    out = filter_overlay_ghosts(frame, ghosts)
    assert out == []


def test_low_confidence_dropped_even_on_object():
    frame = _wood_with_bottle()
    out = filter_overlay_ghosts(
        frame,
        [_det(120, 70, 170, 170, conf=OVERLAY_MIN_CONFIDENCE - 0.1)],
    )
    assert out == []


def test_real_bottle_blob_keeps_overlapping_detection():
    frame = _wood_with_bottle()
    bottle = _det(118, 68, 172, 172, conf=0.94)
    ghost = _det(10, 10, 60, 50, conf=0.80)
    out = filter_overlay_ghosts(frame, [bottle, ghost])
    boxes = [d["bbox"] for d in out]
    assert any(b["x1"] == 118 for b in boxes)
    assert not any(b["x1"] == 10 for b in boxes)


def test_person_kept_on_empty_counter():
    frame = _wood()
    person = {
        "class_name": "person",
        "confidence": 1.0,
        "sku_label": "Khach hang #1",
        "bbox": {"x1": 200, "y1": 20, "x2": 300, "y2": 220},
    }
    out = filter_overlay_ghosts(frame, [person, _det(10, 10, 80, 80, conf=0.9)])
    assert len(out) == 1
    assert out[0]["class_name"] == "person"
