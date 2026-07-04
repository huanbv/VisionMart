"""Classical OpenCV preprocessing steps — CLAHE, histogram equalization,
brightness/contrast, gamma correction, Gaussian/median blur.

Each function takes and returns a BGR ``uint8`` ndarray of the same shape.
All operate on the L channel of LAB (or via a LUT/convertScaleAbs) rather
than per-BGR-channel where relevant, to avoid introducing color casts.
"""

from __future__ import annotations

import numpy as np

from app.vision.config import VisionConfig


def _odd(k: int) -> int:
    """OpenCV's Gaussian/median blur kernel sizes must be odd and >= 1."""
    k = max(1, int(k))
    return k if k % 2 == 1 else k + 1


def apply_clahe(frame_bgr: np.ndarray, clip_limit: float, tile_grid_size: int) -> np.ndarray:
    import cv2

    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=max(0.01, clip_limit),
        tileGridSize=(max(1, tile_grid_size), max(1, tile_grid_size)),
    )
    l_eq = clahe.apply(l_channel)
    merged = cv2.merge((l_eq, a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def apply_hist_eq(frame_bgr: np.ndarray) -> np.ndarray:
    import cv2

    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    l_eq = cv2.equalizeHist(l_channel)
    merged = cv2.merge((l_eq, a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def apply_brightness(frame_bgr: np.ndarray, delta: float) -> np.ndarray:
    import cv2

    return cv2.convertScaleAbs(frame_bgr, alpha=1.0, beta=delta)


def apply_contrast(frame_bgr: np.ndarray, alpha: float) -> np.ndarray:
    import cv2

    return cv2.convertScaleAbs(frame_bgr, alpha=alpha, beta=0.0)


def apply_gamma(frame_bgr: np.ndarray, gamma: float) -> np.ndarray:
    import cv2

    gamma = max(0.01, gamma)
    inv_gamma = 1.0 / gamma
    table = np.array(
        [((i / 255.0) ** inv_gamma) * 255 for i in range(256)], dtype=np.uint8
    )
    return cv2.LUT(frame_bgr, table)


def apply_gaussian_blur(frame_bgr: np.ndarray, kernel_size: int) -> np.ndarray:
    import cv2

    k = _odd(kernel_size)
    return cv2.GaussianBlur(frame_bgr, (k, k), 0)


def apply_median_blur(frame_bgr: np.ndarray, kernel_size: int) -> np.ndarray:
    import cv2

    k = _odd(kernel_size)
    if k <= 1:
        return frame_bgr
    return cv2.medianBlur(frame_bgr, k)


def enhance_frame(frame_bgr: np.ndarray, cfg: VisionConfig) -> np.ndarray:
    """Apply every enabled enhancement step, in a fixed order:
    gamma -> brightness -> contrast -> CLAHE -> hist-eq -> gaussian blur ->
    median blur. Steps are cheap to reorder if a future thesis chapter
    needs a different pipeline order; this order was chosen so tonal
    corrections (gamma/brightness/contrast) happen before contrast-
    normalizing steps (CLAHE/hist-eq), which happen before noise-reduction
    (blur) so blurring doesn't get undone by a later contrast boost.

    Returns the input unchanged if `cfg.any_enhancement_enabled` is False
    (checked by the caller too, but safe to call directly).
    """
    out = frame_bgr
    if cfg.enable_gamma:
        out = apply_gamma(out, cfg.gamma_value)
    if cfg.enable_brightness:
        out = apply_brightness(out, cfg.brightness_delta)
    if cfg.enable_contrast:
        out = apply_contrast(out, cfg.contrast_alpha)
    if cfg.enable_clahe:
        out = apply_clahe(out, cfg.clahe_clip_limit, cfg.clahe_tile_grid_size)
    if cfg.enable_hist_eq:
        out = apply_hist_eq(out)
    if cfg.enable_gaussian_blur:
        out = apply_gaussian_blur(out, cfg.gaussian_kernel_size)
    if cfg.enable_median_blur:
        out = apply_median_blur(out, cfg.median_kernel_size)
    return out
