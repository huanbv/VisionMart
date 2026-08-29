"""Heuristics to tell a checkout blob from wood grain / reflections.

Custom YOLO was trained on full-frame labels, so it happily assigns Sting to
bare counter. Real bottles and packs differ from the counter colour *and*
contain saturated packaging pixels; polished wood highlights are bright but
desaturated.
"""

from __future__ import annotations

from typing import Any


def _median_bg(work: Any):
    import numpy as np

    pixels = work.reshape(-1, 3)
    pixels = pixels[pixels.sum(axis=1) > 24]
    if pixels.shape[0] < 50:
        return None
    return np.median(pixels, axis=0)


def looks_like_product_blob(crop: Any, *, bg_median: Any | None = None) -> bool:
    """True when a contour crop plausibly contains packaging, not table surface."""
    import cv2
    import numpy as np

    if crop is None or getattr(crop, "size", 0) == 0:
        return False
    h, w = crop.shape[:2]
    if min(h, w) < 6:
        return False

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    val = hsv[:, :, 2].astype(np.float32)
    mean_sat = float(sat.mean())
    mean_val = float(val.mean())

    # Specular wood glare — brighter than the counter, almost grey.
    if mean_sat < 45.0 and mean_val > 155.0:
        return False

    crop_mean = crop.reshape(-1, 3).mean(axis=0)
    if bg_median is not None:
        if float(np.abs(crop_mean - bg_median).sum()) < 48.0:
            return False

    # Green 7Up / red Sting / orange mì.
    if mean_sat >= 52.0:
        return True

    # Logo/text islands on a pack inside a dull crop.
    if float((sat >= 58).mean()) >= 0.14 and float(val.std()) > 22.0:
        return True

    if mean_val < 105.0 and float(val.std()) > 30.0 and mean_sat >= 30.0:
        return True

    return False


def median_background(work: Any):
    """Median BGR of non-black ROI pixels — the counter surface colour."""
    return _median_bg(work)
