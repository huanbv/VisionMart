"""Decode raw image bytes into a BGR ``uint8`` ndarray via OpenCV.

Raises ``ValueError`` on undecodable input, matching the
``ValueError`` `person_tracker.track_frame` already raised for bad images
(via PIL's decode failure before this Sprint) — callers' existing
``except ValueError`` handling in `app/api/frame.py` needs no change.
"""

from __future__ import annotations

import numpy as np


def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    import cv2

    buf = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Cannot decode image: not a valid/supported image format")
    return frame
