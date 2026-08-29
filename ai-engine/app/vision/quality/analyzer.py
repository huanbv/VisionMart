"""Frame quality metrics: brightness, contrast, blur (variance of
Laplacian), and a basic noise estimate.

All measurements are computed on a grayscale copy of the frame — cheap
relative to a YOLO forward pass (a handful of OpenCV ops on a single
downsampled-by-nothing frame), but still skippable entirely via
``ENABLE_IMAGE_QUALITY`` / ``ENABLE_BLUR_ANALYSIS`` for deployments that
want zero extra CPU cost per frame.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.vision.config import VisionConfig


@dataclass(frozen=True)
class FrameQuality:
    brightness: float          # mean grayscale intensity, 0-255
    contrast: float            # stddev of grayscale intensity, 0-255ish
    blur_score: float          # variance of Laplacian; higher = sharper
    noise_estimate: float      # mean abs diff vs. a median-blurred copy
    quality_score: float       # combined 0-1 score, see `analyze_quality`
    is_blurry: bool
    is_low_quality: bool
    reason: str | None         # human-readable explanation when flagged


def _variance_of_laplacian(gray: np.ndarray) -> float:
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _noise_estimate(gray: np.ndarray) -> float:
    """Very rough noise estimate: how much the frame differs from a
    median-blurred (noise-suppressed) version of itself. Not a substitute
    for a proper noise model (e.g. wavelet-based estimators) — flagged in
    the Sprint 2 recommendations as an area to revisit if noise turns out
    to matter in practice for this store's cameras."""
    import cv2

    denoised = cv2.medianBlur(gray, 3)
    return float(np.mean(np.abs(gray.astype(np.int16) - denoised.astype(np.int16))))


def analyze_quality(frame_bgr: np.ndarray, cfg: VisionConfig) -> FrameQuality:
    import cv2

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    blur_score = _variance_of_laplacian(gray) if cfg.enable_blur_analysis else float("nan")
    noise = _noise_estimate(gray) if cfg.enable_image_quality else float("nan")

    # Normalized sub-scores, each roughly 0 (bad) - 1 (good). Deliberately
    # simple/explainable (equal-weighted average) rather than a learned or
    # heavily-tuned formula — appropriate for a thesis-scope quality gate,
    # not a production imaging pipeline.
    brightness_norm = brightness / 255.0
    brightness_score = max(0.0, 1.0 - abs(brightness_norm - 0.5) * 2.0)
    contrast_score = min(1.0, contrast / 64.0)
    if cfg.enable_blur_analysis:
        blur_norm_score = min(1.0, blur_score / (2.0 * max(cfg.blur_threshold, 1.0)))
        quality_score = (brightness_score + contrast_score + blur_norm_score) / 3.0
    else:
        quality_score = (brightness_score + contrast_score) / 2.0

    is_blurry = cfg.enable_blur_analysis and blur_score < cfg.blur_threshold
    is_low_quality = quality_score < cfg.image_quality_threshold or is_blurry

    reason = None
    if is_blurry:
        reason = f"blur_score {blur_score:.1f} < threshold {cfg.blur_threshold:.1f}"
    elif is_low_quality:
        reason = (
            f"quality_score {quality_score:.2f} < threshold "
            f"{cfg.image_quality_threshold:.2f}"
        )

    return FrameQuality(
        brightness=brightness,
        contrast=contrast,
        blur_score=blur_score,
        noise_estimate=noise,
        quality_score=quality_score,
        is_blurry=is_blurry,
        is_low_quality=is_low_quality,
        reason=reason,
    )
