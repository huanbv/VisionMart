"""Shared result container passed from `evaluation/cli.py` (or a Python
caller) into the exporters/chart/report generators in this package.

Deliberately a plain dict-of-dicts under the hood (`to_dict()`) rather
than a rigid schema class, because different runs legitimately populate
different subsets of it (e.g. a run without --with-yolo has no
`detection`/`tracking` keys per config; a run without --db-url has no
`cart_metrics` at all) -- every consumer here must handle missing keys by
reporting "not measured", never by defaulting to zero.
"""

from __future__ import annotations

import dataclasses
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def to_plain(obj: Any) -> Any:
    """Recursively converts dataclasses (and containers of them) to plain
    dicts/lists so the result is directly JSON-serializable and easy to
    flatten into DataFrames, without every producer needing to remember to
    call `dataclasses.asdict` itself."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_plain(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


@dataclass
class ConfigRunResult:
    """Everything measured for ONE of the 7 preprocessing configurations,
    on one dataset run."""

    config_id: int
    config_name: str
    pipeline: dict                      # PipelineMetricsCollector.summary()
    camera_quality: dict | None = None  # CameraQualityCollector.summary()
    detection: dict | None = None       # DetectionMetricsResult, via to_plain()
    tracking: dict | None = None        # TrackingMetricsResult, via to_plain()


@dataclass
class RunResult:
    run_id: str
    generated_at: str
    dataset: dict = field(default_factory=dict)       # {"kind", "path", "frame_count", "source_description"}
    environment: dict = field(default_factory=dict)   # {"python", "platform", "with_yolo", "labels_used", ...}
    configs: list[ConfigRunResult] = field(default_factory=list)
    opencv_modules: list[dict] | None = None           # list of ModuleResult, via to_plain()
    cart_metrics: dict | None = None                   # CartMetricsResult, via to_plain() -- from the separate DB subprocess

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "dataset": self.dataset,
            "environment": self.environment,
            "configs": [to_plain(c) for c in self.configs],
            "opencv_modules": to_plain(self.opencv_modules) if self.opencv_modules is not None else None,
            "cart_metrics": to_plain(self.cart_metrics) if self.cart_metrics is not None else None,
        }


def new_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _read_app_version() -> str:
    """Reads the centralized `VERSION` file at the repo root (see
    docs/44_VERSIONING.md) so every exported report (JSON/CSV/XLSX/
    Markdown/thesis) records exactly which VisionMart version produced
    it. `evaluation/` runs directly against a repo checkout (no separate
    Docker image), so a plain relative path is sufficient here -- this
    file is `evaluation/reporting/types.py`, so the repo root is two
    levels up."""
    path = Path(__file__).resolve().parents[2] / "VERSION"
    if not path.exists():
        return "unknown"
    try:
        return path.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def default_environment(*, with_yolo: bool, labels_used: str | None) -> dict:
    return {
        "visionmart_version": _read_app_version(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "with_yolo": with_yolo,
        "labels_used": labels_used,
    }
