"""The 7 preprocessing configurations compared by every evaluation run,
plus the individual OpenCV modules evaluated in isolation (§ "OPENCV
EVALUATION" in the framework brief).

Single source of truth — `runner.py`, `reporting/*`, and the thesis report
all import `PREPROCESSING_CONFIGS` / `OPENCV_MODULES` from here rather than
each defining their own copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PreprocessingConfig:
    id: int
    name: str
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""


PREPROCESSING_CONFIGS: tuple[PreprocessingConfig, ...] = (
    PreprocessingConfig(1, "Baseline (No OpenCV preprocessing)", {}, "Decode only — identical to Sprint 1's pre-existing default."),
    PreprocessingConfig(
        2,
        "Brightness / Contrast",
        {
            "ENABLE_BRIGHTNESS_ADJUST": "true", "BRIGHTNESS_DELTA": "15",
            "ENABLE_CONTRAST_ADJUST": "true", "CONTRAST_ALPHA": "1.2",
        },
        "Additive brightness + multiplicative contrast, cheapest enhancement pair.",
    ),
    PreprocessingConfig(3, "Gamma Correction", {"ENABLE_GAMMA": "true", "GAMMA_VALUE": "1.5"}, "LUT-based gamma correction."),
    PreprocessingConfig(4, "CLAHE", {"ENABLE_CLAHE": "true"}, "Adaptive histogram equalization on the LAB L-channel."),
    PreprocessingConfig(5, "Histogram Equalization", {"ENABLE_HIST_EQ": "true"}, "Global histogram equalization on the LAB L-channel."),
    PreprocessingConfig(
        6, "CLAHE + Gamma",
        {"ENABLE_CLAHE": "true", "ENABLE_GAMMA": "true", "GAMMA_VALUE": "1.5"},
        "Combination requested to check whether Gamma adds meaningful cost on top of CLAHE.",
    ),
    PreprocessingConfig(
        7, "Full OpenCV Pipeline",
        {
            "ENABLE_ROI": "true",
            "ENABLE_CLAHE": "true",
            "ENABLE_HIST_EQ": "true",
            "ENABLE_BRIGHTNESS_ADJUST": "true", "BRIGHTNESS_DELTA": "15",
            "ENABLE_CONTRAST_ADJUST": "true", "CONTRAST_ALPHA": "1.2",
            "ENABLE_GAMMA": "true", "GAMMA_VALUE": "1.5",
            "ENABLE_GAUSSIAN_BLUR": "true",
            "ENABLE_MEDIAN_BLUR": "true",
            "ENABLE_IMAGE_QUALITY": "true",
            "ENABLE_BLUR_ANALYSIS": "true",
        },
        "Every vision/ Module 2-4 feature enabled simultaneously — worst-case cost scenario.",
    ),
)


@dataclass(frozen=True)
class OpenCvModule:
    key: str          # the ENABLE_* flag name this module is gated by
    name: str
    extra_env: dict[str, str] = field(default_factory=dict)


OPENCV_MODULES: tuple[OpenCvModule, ...] = (
    OpenCvModule("ENABLE_ROI", "ROI Masking"),
    OpenCvModule("ENABLE_CLAHE", "CLAHE"),
    OpenCvModule("ENABLE_HIST_EQ", "Histogram Equalization"),
    OpenCvModule("ENABLE_BRIGHTNESS_ADJUST", "Brightness Adjustment", {"BRIGHTNESS_DELTA": "15"}),
    OpenCvModule("ENABLE_CONTRAST_ADJUST", "Contrast Adjustment", {"CONTRAST_ALPHA": "1.2"}),
    OpenCvModule("ENABLE_GAMMA", "Gamma Correction", {"GAMMA_VALUE": "1.5"}),
    OpenCvModule("ENABLE_GAUSSIAN_BLUR", "Gaussian Blur"),
    OpenCvModule("ENABLE_MEDIAN_BLUR", "Median Blur"),
    OpenCvModule("ENABLE_BILATERAL", "Bilateral Filter (edge-preserving denoise)"),
    OpenCvModule("ENABLE_UNSHARP_MASK", "Unsharp Masking (sharpening)", {"UNSHARP_AMOUNT": "0.6"}),
    OpenCvModule("ENABLE_AUTO_GAMMA", "Auto Gamma (per-frame exposure correction)"),
    OpenCvModule("ENABLE_ADAPTIVE_MEDIAN", "Adaptive Median (impulse noise)"),
    OpenCvModule("ENABLE_IMAGE_QUALITY", "Image Quality Analysis (incl. Blur Analysis)", {"ENABLE_BLUR_ANALYSIS": "true"}),
)
