"""Classical OpenCV preprocessing steps — CLAHE, histogram equalization,
brightness/contrast, gamma correction, Gaussian/median blur, plus the
edge-preserving / sharpening / adaptive family added in Sprint 2
(bilateral, unsharp masking, auto-gamma, adaptive median).

Each function takes and returns a BGR ``uint8`` ndarray of the same shape.
All operate on the L channel of LAB (or via a LUT/convertScaleAbs) rather
than per-BGR-channel where relevant, to avoid introducing color casts.

Textbook mapping (Gonzalez & Woods, *Digital Image Processing*, 4th ed.):

* gamma / brightness / contrast   — Ch.3 intensity transformations
* histogram equalization, CLAHE   — Ch.3 histogram processing
* Gaussian / median blur          — Ch.3 smoothing spatial filters
* bilateral filter                — edge-preserving smoothing; the only
  smoother in the comparison table that keeps object edges sharp, which
  matters here because blurred edges cost detector accuracy
* unsharp masking / highboost     — Ch.3 sharpening (eq. 3.6-8/3.6-9)
* adaptive median                 — Ch.5 restoration, handles impulse
  noise at higher densities than a fixed-window median
* auto gamma                      — practical extension: picks the gamma
  exponent per frame from measured brightness instead of a fixed constant,
  so one config works across day/night lighting on the same camera
"""

from __future__ import annotations

from typing import Any

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


def apply_bilateral(
    frame_bgr: np.ndarray, diameter: int, sigma_color: float, sigma_space: float
) -> np.ndarray:
    """Edge-preserving denoise. Unlike Gaussian/median, pixels only average
    with neighbours of *similar intensity*, so object edges stay sharp
    while flat areas get smoothed — the property that matters when the
    consumer of this frame is an object detector rather than a human.

    Cost note: the most expensive smoother here (roughly an order of
    magnitude over Gaussian at the same radius); `evaluation/` measures
    this per-module so the cost shows up explicitly rather than as an
    unexplained FPS drop.
    """
    import cv2

    return cv2.bilateralFilter(
        frame_bgr,
        d=max(1, int(diameter)),
        sigmaColor=max(1.0, sigma_color),
        sigmaSpace=max(1.0, sigma_space),
    )


def apply_unsharp_mask(
    frame_bgr: np.ndarray, amount: float, radius: int, threshold: int = 0
) -> np.ndarray:
    """Unsharp masking / highboost filtering: ``g = f + amount * (f - blur(f))``.

    ``amount = 1.0`` is textbook unsharp masking; ``> 1`` is highboost.
    Large values create halos around edges, so the caller-facing default
    stays conservative. ``threshold`` (0-255) suppresses sharpening of
    low-contrast differences, which otherwise amplifies sensor noise in
    dark frames — the failure mode that makes naive sharpening hurt
    detection instead of helping it.
    """
    import cv2

    blurred = cv2.GaussianBlur(frame_bgr, (0, 0), sigmaX=max(0.1, float(radius)))
    if threshold <= 0:
        return cv2.addWeighted(frame_bgr, 1.0 + amount, blurred, -amount, 0.0)

    # Only sharpen where |f - blur| exceeds the threshold.
    diff = cv2.absdiff(frame_bgr, blurred)
    mask = (diff.max(axis=2) >= int(threshold)).astype(np.uint8)
    sharpened = cv2.addWeighted(frame_bgr, 1.0 + amount, blurred, -amount, 0.0)
    mask3 = cv2.cvtColor(mask * 255, cv2.COLOR_GRAY2BGR).astype(bool)
    return np.where(mask3, sharpened, frame_bgr)


def compute_auto_gamma(
    frame_bgr: np.ndarray, target_brightness: float, min_gamma: float, max_gamma: float
) -> float:
    """Pick the gamma exponent that moves this frame's mean luminance toward
    ``target_brightness``.

    Solving ``(mean/255) ** (1/gamma) == target/255`` for gamma gives
    ``gamma = log(mean/255) / log(target/255)``. The result is clamped so a
    nearly-black or blown-out frame can't request an extreme correction.

    Returned in the same convention as ``apply_gamma`` (>1 brightens).
    """
    import cv2

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    target = min(254.0, max(1.0, float(target_brightness)))
    if mean <= 1.0 or mean >= 254.0:
        return 1.0
    gamma = np.log(mean / 255.0) / np.log(target / 255.0)
    if not np.isfinite(gamma) or gamma <= 0:
        return 1.0
    return float(min(max_gamma, max(min_gamma, gamma)))


def apply_adaptive_median(frame_bgr: np.ndarray, max_kernel_size: int) -> np.ndarray:
    """Adaptive median filter (Gonzalez & Woods Ch.5).

    A fixed-window median replaces *every* pixel; this one grows the window
    only where the median itself still looks like impulse noise, and leaves
    non-impulse pixels untouched — so it removes salt-and-pepper at higher
    densities while preserving detail a plain median would erase.

    Implemented as a vectorised approximation of the textbook's per-pixel
    algorithm: for each window size, pixels still classified as impulse
    (equal to the local min or max) are replaced from that scale's median,
    and already-resolved pixels are frozen. This keeps the cost to a few
    ``cv2.medianBlur`` passes rather than a Python loop over every pixel.
    """
    import cv2

    max_k = _odd(max_kernel_size)
    if max_k <= 1:
        return frame_bgr

    out = frame_bgr.copy()
    # Pixels not yet resolved — start with those that look like impulses.
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    unresolved = (gray <= 2) | (gray >= 253)

    k = 3
    while k <= max_k and unresolved.any():
        med = cv2.medianBlur(out, k)
        med_gray = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY)
        # Where this scale's median is itself not an impulse, accept it.
        usable = unresolved & (med_gray > 2) & (med_gray < 253)
        if usable.any():
            out[usable] = med[usable]
            unresolved = unresolved & ~usable
        k += 2

    if unresolved.any():  # still unresolved at max window: take the widest median
        med = cv2.medianBlur(out, max_k)
        out[unresolved] = med[unresolved]
    return out


def enhance_frame(
    frame_bgr: np.ndarray, cfg: VisionConfig, recorder: Any | None = None
) -> np.ndarray:
    """Apply every enabled enhancement step, in a fixed order:
    gamma -> brightness -> contrast -> CLAHE -> hist-eq -> gaussian blur ->
    median blur. Steps are cheap to reorder if a future thesis chapter
    needs a different pipeline order; this order was chosen so tonal
    corrections (gamma/brightness/contrast) happen before contrast-
    normalizing steps (CLAHE/hist-eq), which happen before noise-reduction
    (blur) so blurring doesn't get undone by a later contrast boost.

    Returns the input unchanged if `cfg.any_enhancement_enabled` is False
    (checked by the caller too, but safe to call directly).

    Sprint 2 additions slot into that same rationale: auto-gamma is a tonal
    correction so it sits with gamma; bilateral / adaptive-median are
    noise-reduction so they join the blur group; unsharp masking runs
    *last* because sharpening before a smoother would simply be undone by
    it (and sharpening before CLAHE would get its halos amplified).

    ``recorder``, when supplied, gets one snapshot per *enabled* stage so
    the admin trace view can show what each individual step changed —
    without it this function behaves exactly as before.
    """
    out = frame_bgr

    def _step(stage: str, label: str, result: np.ndarray, **params) -> np.ndarray:
        if recorder is not None:
            recorder.capture(stage, label, result, params)
        return result

    if cfg.enable_auto_gamma:
        # Measured from the incoming frame, so it adapts per frame rather
        # than baking one exposure assumption into the config.
        g = compute_auto_gamma(
            out,
            cfg.auto_gamma_target_brightness,
            cfg.auto_gamma_min,
            cfg.auto_gamma_max,
        )
        out = _step("auto_gamma", "Auto gamma", apply_gamma(out, g), gamma=round(g, 3))
    elif cfg.enable_gamma:
        out = _step(
            "gamma", "Gamma", apply_gamma(out, cfg.gamma_value), gamma=cfg.gamma_value
        )
    if cfg.enable_brightness:
        out = _step(
            "brightness", "Brightness", apply_brightness(out, cfg.brightness_delta),
            delta=cfg.brightness_delta,
        )
    if cfg.enable_contrast:
        out = _step(
            "contrast", "Contrast", apply_contrast(out, cfg.contrast_alpha),
            alpha=cfg.contrast_alpha,
        )
    if cfg.enable_clahe:
        out = _step(
            "clahe", "CLAHE",
            apply_clahe(out, cfg.clahe_clip_limit, cfg.clahe_tile_grid_size),
            clip_limit=cfg.clahe_clip_limit, tile_grid_size=cfg.clahe_tile_grid_size,
        )
    if cfg.enable_hist_eq:
        out = _step("hist_eq", "Histogram equalization", apply_hist_eq(out))
    if cfg.enable_gaussian_blur:
        out = _step(
            "gaussian_blur", "Gaussian blur",
            apply_gaussian_blur(out, cfg.gaussian_kernel_size),
            kernel_size=cfg.gaussian_kernel_size,
        )
    if cfg.enable_median_blur:
        out = _step(
            "median_blur", "Median blur",
            apply_median_blur(out, cfg.median_kernel_size),
            kernel_size=cfg.median_kernel_size,
        )
    if cfg.enable_adaptive_median:
        out = _step(
            "adaptive_median", "Adaptive median",
            apply_adaptive_median(out, cfg.adaptive_median_max_kernel),
            max_kernel=cfg.adaptive_median_max_kernel,
        )
    if cfg.enable_bilateral:
        out = _step(
            "bilateral", "Bilateral filter",
            apply_bilateral(
                out, cfg.bilateral_diameter, cfg.bilateral_sigma_color,
                cfg.bilateral_sigma_space,
            ),
            diameter=cfg.bilateral_diameter, sigma_color=cfg.bilateral_sigma_color,
            sigma_space=cfg.bilateral_sigma_space,
        )
    if cfg.enable_unsharp_mask:
        out = _step(
            "unsharp_mask", "Unsharp masking",
            apply_unsharp_mask(
                out, cfg.unsharp_amount, cfg.unsharp_radius, cfg.unsharp_threshold
            ),
            amount=cfg.unsharp_amount, radius=cfg.unsharp_radius,
            threshold=cfg.unsharp_threshold,
        )
    return out
