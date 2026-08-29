"""Module 6 — optional debug visualization overlay.

Disabled by default (`ENABLE_DEBUG_OVERLAY=false`) and never invoked unless
a caller explicitly asks for it (see `pipeline.py`) — drawing cost is zero
in production mode, not just "small".
"""

from __future__ import annotations

from app.vision.overlay.debug_overlay import OverlayDetection, draw_debug_overlay

__all__ = ["OverlayDetection", "draw_debug_overlay"]
