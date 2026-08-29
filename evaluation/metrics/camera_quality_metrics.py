"""Camera / image quality metrics.

Brightness, contrast, and blur reuse the exact same computation as
production (`ai-engine/app/vision/quality/analyzer.py`) so numbers from
this framework are directly comparable to what the live system would
compute for the same frame. Motion percentage and frozen-frame detection
are new, evaluation-only additions (frame-to-frame comparisons don't make
sense inside the per-frame production pipeline, which has no guaranteed
access to the previous frame across requests).

Camera "uptime" is intentionally NOT computed here — it's a fleet/time-
series concept (was the camera reachable over some historical window),
not something derivable from a batch of already-captured frames. See
`evaluation/cart/cart_metrics.py` for the read-only DB query that computes
it from the backend's camera health data, when a DB connection is
available.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import numpy as np


@dataclass
class QualitySample:
    frame_name: str
    brightness: float
    contrast: float
    blur_score: float
    noise_estimate: float
    quality_score: float
    is_low_quality: bool
    motion_percent: float | None   # None for the first frame (no predecessor)
    is_frozen: bool                 # near-identical to the previous frame


class CameraQualityCollector:
    def __init__(self, blur_threshold: float = 100.0, quality_threshold: float = 0.5, frozen_diff_threshold: float = 0.5) -> None:
        # frozen_diff_threshold: mean-abs-diff (0-255 scale) below this,
        # between consecutive grayscale frames, is treated as "frozen"
        # (camera stuck / feed stalled) rather than "just a static scene" —
        # real static retail scenes still have sensor noise producing a
        # small but nonzero diff; a truly frozen feed re-serves the exact
        # same bytes.
        self.blur_threshold = blur_threshold
        self.quality_threshold = quality_threshold
        self.frozen_diff_threshold = frozen_diff_threshold
        self.samples: list[QualitySample] = []
        self._prev_gray: np.ndarray | None = None

    def observe(self, frame_name: str, frame_bgr: np.ndarray) -> QualitySample:
        import cv2

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        denoised = cv2.medianBlur(gray, 3)
        noise = float(np.mean(np.abs(gray.astype(np.int16) - denoised.astype(np.int16))))

        brightness_score = max(0.0, 1.0 - abs(brightness / 255.0 - 0.5) * 2.0)
        contrast_score = min(1.0, contrast / 64.0)
        blur_norm_score = min(1.0, blur_score / (2.0 * max(self.blur_threshold, 1.0)))
        quality_score = (brightness_score + contrast_score + blur_norm_score) / 3.0
        is_low_quality = quality_score < self.quality_threshold or blur_score < self.blur_threshold

        motion_percent = None
        is_frozen = False
        if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            diff = cv2.absdiff(gray, self._prev_gray)
            mean_diff = float(np.mean(diff))
            # Motion % : fraction of pixels that changed more than a small
            # noise-floor threshold (25/255) between consecutive frames.
            changed = float(np.mean(diff > 25)) * 100.0
            motion_percent = round(changed, 2)
            is_frozen = mean_diff < self.frozen_diff_threshold
        self._prev_gray = gray

        sample = QualitySample(
            frame_name=frame_name,
            brightness=round(brightness, 2),
            contrast=round(contrast, 2),
            blur_score=round(blur_score, 2),
            noise_estimate=round(noise, 3),
            quality_score=round(quality_score, 3),
            is_low_quality=is_low_quality,
            motion_percent=motion_percent,
            is_frozen=is_frozen,
        )
        self.samples.append(sample)
        return sample

    def summary(self) -> dict:
        if not self.samples:
            return {}
        brightness = [s.brightness for s in self.samples]
        contrast = [s.contrast for s in self.samples]
        blur = [s.blur_score for s in self.samples]
        noise = [s.noise_estimate for s in self.samples]
        quality = [s.quality_score for s in self.samples]
        motion = [s.motion_percent for s in self.samples if s.motion_percent is not None]
        frozen_count = sum(1 for s in self.samples if s.is_frozen)
        low_quality_count = sum(1 for s in self.samples if s.is_low_quality)

        return {
            "frame_count": len(self.samples),
            "brightness_avg": round(statistics.mean(brightness), 2),
            "brightness_min": round(min(brightness), 2),
            "brightness_max": round(max(brightness), 2),
            "contrast_avg": round(statistics.mean(contrast), 2),
            "blur_score_avg": round(statistics.mean(blur), 2),
            "blur_score_min": round(min(blur), 2),
            "noise_estimate_avg": round(statistics.mean(noise), 3),
            "quality_score_avg": round(statistics.mean(quality), 3),
            "low_quality_frame_count": low_quality_count,
            "low_quality_frame_pct": round(100.0 * low_quality_count / len(self.samples), 1),
            "motion_percent_avg": round(statistics.mean(motion), 2) if motion else None,
            "frozen_frame_count": frozen_count,
            "frozen_frame_pct": round(100.0 * frozen_count / len(self.samples), 1),
        }
