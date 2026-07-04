"""Module 4 — frame quality analysis.

Measures brightness, contrast, blur (variance of Laplacian), and a basic
noise estimate; combines them into a single 0-1 quality score. Poor-quality
frames are flagged (`FrameQuality.is_low_quality`) — never silently
discarded. What the caller does with that flag (log it, surface it on a
dashboard, skip AI-event emission for that frame) is a decision left to the
caller; this module only measures and reports.
"""

from __future__ import annotations

from app.vision.quality.analyzer import FrameQuality, analyze_quality

__all__ = ["FrameQuality", "analyze_quality"]
