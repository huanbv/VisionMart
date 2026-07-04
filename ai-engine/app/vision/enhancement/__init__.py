"""Module 3 — optional classical image enhancement, applied before YOLO.

Every step here is independently toggleable via `app.vision.config`. When
none are enabled (the default), `enhance_frame` returns the input frame
completely unchanged — same bytes, no copy, no cost.
"""

from __future__ import annotations

from app.vision.enhancement.enhance import enhance_frame

__all__ = ["enhance_frame"]
