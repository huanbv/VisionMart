from __future__ import annotations

import numpy as np

from app.vision.overlay.live_markers import (
    collapse_nearby_products,
    draw_live_detections,
)


def _product(x1, y1, x2, y2, sku="Sting đỏ", conf=0.8, cls="du_sti"):
    return {
        "class_name": cls,
        "confidence": conf,
        "sku_label": sku,
        "sku_confidence": conf,
        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
    }


def test_product_overlay_does_not_stroke_giant_box():
    """A full-frame bbox must not paint a rectangle around the counter."""
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    draw_live_detections(frame, [_product(8, 8, 392, 192, conf=0.84)])
    # Corners of that giant box stay dark — no rectangle outline.
    assert int(frame[8, 8].sum()) < 40
    assert int(frame[8, 391].sum()) < 40
    assert int(frame[191, 8].sum()) < 40
    # Center (dot) is painted.
    assert int(frame[100, 200].sum()) > 80


def test_person_keeps_thin_box():
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    draw_live_detections(
        frame,
        [
            {
                "class_name": "person",
                "confidence": 1.0,
                "sku_label": "Khach hang #1",
                "sku_confidence": 1.0,
                "bbox": {"x1": 40, "y1": 30, "x2": 180, "y2": 170},
            }
        ],
    )
    # Top edge of the person box is stroked.
    assert int(frame[30, 80].sum()) > 40


def test_person_wrist_dots_drawn():
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    draw_live_detections(
        frame,
        [
            {
                "class_name": "person",
                "confidence": 1.0,
                "sku_label": "Khach hang #1",
                "bbox": {"x1": 40, "y1": 30, "x2": 180, "y2": 170},
                "left_hand": (100, 120),
                "right_hand": (140, 125),
                "left_elbow": (90, 90),
                "right_elbow": (150, 95),
            }
        ],
    )
    assert int(frame[120, 100].sum()) > 80
    assert int(frame[125, 140].sum()) > 80
    # Hand box around the wrist.
    assert int(frame[120, 100 - 11].sum()) > 40


def test_collapse_same_sku_nearby():
    a = (100, 100, 0.9, _product(80, 80, 120, 120, conf=0.9))
    b = (108, 104, 0.4, _product(90, 90, 130, 130, conf=0.4))
    kept = collapse_nearby_products([a, b], min_dist=28)
    assert len(kept) == 1
    assert kept[0][2] == 0.9


def test_collapse_nearby_different_skus_on_same_object():
    """7Up + Sting on one bottle must not draw two HUD labels."""
    a = (100, 100, 0.9, _product(80, 80, 120, 120, sku="Sting đỏ", conf=0.9))
    b = (108, 104, 0.8, _product(90, 90, 130, 130, sku="7Up", cls="du_7u", conf=0.8))
    kept = collapse_nearby_products([a, b], min_dist=28)
    assert len(kept) == 1
    assert kept[0][2] == 0.9
