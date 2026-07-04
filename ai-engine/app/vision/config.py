"""Environment-driven configuration for the vision/ package.

Follows the same convention already used elsewhere in this service (see
`app/api/frame.py`'s ``os.getenv`` helpers) rather than introducing a new
settings framework: every toggle defaults to *off* / a value that makes
`pipeline.py` behave exactly like the pre-Sprint code path (plain decode,
no ROI, no enhancement). Nothing here requires a code change to flip —
only environment variables.

Read once per process into a module-level singleton (`get_vision_config()`)
rather than re-parsing env vars on every frame; call `reload()` (tests only)
to force a re-read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    return int(_float(name, float(default)))


def _str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return default if raw is None else raw


@dataclass(frozen=True)
class VisionConfig:
    # ---- Module 2: ROI ----
    enable_roi: bool = field(default_factory=lambda: _bool("ENABLE_ROI", False))
    roi_config_path: str = field(default_factory=lambda: _str("ROI_CONFIG_PATH", ""))

    # ---- Module 3: Enhancement (each independently toggleable, all off by default) ----
    enable_clahe: bool = field(default_factory=lambda: _bool("ENABLE_CLAHE", False))
    clahe_clip_limit: float = field(default_factory=lambda: _float("CLAHE_CLIP_LIMIT", 2.0))
    clahe_tile_grid_size: int = field(default_factory=lambda: _int("CLAHE_TILE_GRID_SIZE", 8))

    enable_hist_eq: bool = field(default_factory=lambda: _bool("ENABLE_HIST_EQ", False))

    enable_brightness: bool = field(
        default_factory=lambda: _bool("ENABLE_BRIGHTNESS_ADJUST", False)
    )
    # Additive delta in [-255, 255] applied to every pixel.
    brightness_delta: float = field(default_factory=lambda: _float("BRIGHTNESS_DELTA", 0.0))

    enable_contrast: bool = field(
        default_factory=lambda: _bool("ENABLE_CONTRAST_ADJUST", False)
    )
    # Multiplicative gain; 1.0 = no change.
    contrast_alpha: float = field(default_factory=lambda: _float("CONTRAST_ALPHA", 1.0))

    enable_gamma: bool = field(default_factory=lambda: _bool("ENABLE_GAMMA", False))
    gamma_value: float = field(default_factory=lambda: _float("GAMMA_VALUE", 1.0))

    enable_gaussian_blur: bool = field(
        default_factory=lambda: _bool("ENABLE_GAUSSIAN_BLUR", False)
    )
    gaussian_kernel_size: int = field(
        default_factory=lambda: _int("GAUSSIAN_KERNEL_SIZE", 5)
    )

    enable_median_blur: bool = field(
        default_factory=lambda: _bool("ENABLE_MEDIAN_BLUR", False)
    )
    median_kernel_size: int = field(default_factory=lambda: _int("MEDIAN_KERNEL_SIZE", 5))

    # ---- Module 4: Quality analysis ----
    enable_image_quality: bool = field(
        default_factory=lambda: _bool("ENABLE_IMAGE_QUALITY", False)
    )
    enable_blur_analysis: bool = field(
        default_factory=lambda: _bool("ENABLE_BLUR_ANALYSIS", False)
    )
    # Variance-of-Laplacian below this is flagged as "blurry". Tuned for
    # 720p-ish retail camera frames; recalibrate per camera if needed.
    blur_threshold: float = field(default_factory=lambda: _float("BLUR_THRESHOLD", 100.0))
    # Overall 0-1 quality_score below this is flagged as "poor quality".
    image_quality_threshold: float = field(
        default_factory=lambda: _float("IMAGE_QUALITY_THRESHOLD", 0.5)
    )

    # ---- Module 5: Performance metrics ----
    enable_performance_metrics: bool = field(
        default_factory=lambda: _bool("ENABLE_PERFORMANCE_METRICS", False)
    )

    # ---- Module 6: Debug overlay ----
    enable_debug_overlay: bool = field(
        default_factory=lambda: _bool("ENABLE_DEBUG_OVERLAY", False)
    )

    @property
    def any_enhancement_enabled(self) -> bool:
        return (
            self.enable_clahe
            or self.enable_hist_eq
            or self.enable_brightness
            or self.enable_contrast
            or self.enable_gamma
            or self.enable_gaussian_blur
            or self.enable_median_blur
        )


_CONFIG: VisionConfig | None = None


def get_vision_config() -> VisionConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = VisionConfig()
    return _CONFIG


def reload_vision_config() -> VisionConfig:
    """Force a re-read of environment variables. Only needed by tests /
    tools that mutate env vars at runtime — normal request handling uses
    the cached singleton from `get_vision_config()`."""
    global _CONFIG
    _CONFIG = VisionConfig()
    return _CONFIG
