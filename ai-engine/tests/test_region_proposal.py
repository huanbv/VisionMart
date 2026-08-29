from __future__ import annotations

import cv2
import numpy as np

from app.vision.region_proposal import propose_regions


def test_heterogeneous_checkout_falls_back_to_local_contrast():
    """A perspective ROI must not collapse into one full-counter crop."""
    h, w = 240, 320
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    roi = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(
        roi,
        [np.array([[20, 60], [290, 60], [319, 220], [0, 220]], np.int32)],
        255,
    )

    yy, xx = np.indices((h, w))
    counter = np.stack(
        [35 + xx // 7, 55 + xx // 9, 105 + yy // 5], axis=2
    ).clip(1, 240).astype(np.uint8)
    frame[roi > 0] = counter[roi > 0]
    cv2.rectangle(frame, (100, 100), (124, 190), (30, 35, 210), -1)
    cv2.rectangle(frame, (150, 115), (179, 190), (50, 180, 45), -1)
    # Simulate a person torso removed before region proposal.
    cv2.rectangle(frame, (185, 60), (260, 135), (0, 0, 0), -1)

    regions = propose_regions(
        frame,
        min_area_frac=0.0012,
        max_area_frac=0.22,
        max_regions=12,
        bg_tolerance=38,
    )

    assert not any((r.x2 - r.x1) >= 0.8 * w for r in regions)
    assert any(r.x1 <= 112 <= r.x2 and r.y1 <= 145 <= r.y2 for r in regions)
    assert any(r.x1 <= 165 <= r.x2 and r.y1 <= 150 <= r.y2 for r in regions)


def test_empty_wood_without_local_fallback_has_no_regions():
    """Ghost filter turns this off so YOLO hits on grain do not survive."""
    h, w = 240, 320
    yy, xx = np.indices((h, w))
    frame = np.stack(
        [35 + xx // 7, 55 + xx // 9, 105 + yy // 5], axis=2
    ).clip(1, 240).astype(np.uint8)
    regions = propose_regions(
        frame,
        min_area_frac=0.0012,
        max_area_frac=0.22,
        max_regions=12,
        bg_tolerance=38,
        allow_local_fallback=False,
    )
    assert regions == []
