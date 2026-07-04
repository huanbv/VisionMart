"""Shared decode step: raw image bytes -> BGR ``uint8`` ndarray.

Replaces the ad-hoc ``PIL.Image.open(...).convert("RGB")`` that
`person_tracker.py` used to do inline. Decoding to a BGR ndarray via
OpenCV (instead of a PIL RGB image) is what makes the rest of `vision/`
possible (ROI masking, enhancement, quality analysis all operate on
ndarrays) — see `pipeline.py` for the important note on why handing
ultralytics a raw BGR ndarray (instead of a PIL image) is safe and does
NOT need an extra RGB conversion.
"""

from __future__ import annotations

from app.vision.preprocessing.decode import decode_image_bytes

__all__ = ["decode_image_bytes"]
