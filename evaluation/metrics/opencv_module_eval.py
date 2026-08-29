"""Per-module OpenCV cost/benefit evaluation.

Isolates exactly ONE `ENABLE_*` flag at a time (same isolation technique
`ai-engine/scripts/sprint1_evaluation.py` used for whole configurations)
and measures its cost against a Baseline run on the same frames. Benefit
(detection/tracking improvement) is only computed when real YOLO output
is available for both the baseline and the module run — if it isn't, this
module says so explicitly per-module rather than guessing, and the
recommendation logic refuses to recommend "ON" without measured benefit,
per the framework's explicit "Do not recommend enabling modules without
measurable benefit" requirement.
"""

from __future__ import annotations

import os
import statistics
from dataclasses import dataclass

from evaluation.config import OPENCV_MODULES, OpenCvModule


def _reset_and_apply_env(env: dict[str, str]) -> None:
    """Mirrors sprint1_evaluation.py's isolation pattern: clear every
    ENABLE_* / known VisionConfig flag from os.environ, then apply exactly
    the flags for this run, before calling reload_vision_config()."""
    from app.vision.config import VisionConfig, reload_vision_config

    known_flags = [k.upper() for k in vars(VisionConfig()).keys()]
    for k in list(os.environ.keys()):
        if k.startswith("ENABLE_") or k in known_flags:
            os.environ.pop(k, None)
    os.environ.update(env)
    reload_vision_config()


def _run_opencv_only(frames: list[tuple[str, bytes]], env: dict[str, str], camera_key: str) -> list[float]:
    from app.vision.pipeline import preprocess_for_detection

    _reset_and_apply_env(env)
    from app.vision.config import get_vision_config

    cfg = get_vision_config()
    return [preprocess_for_detection(b, camera_key, cfg).opencv_ms for _, b in frames]


def _run_with_yolo(
    frames: list[tuple[str, bytes]], env: dict[str, str], camera_key: str, yolo_model
) -> tuple[list[float], list[dict[str, int]]]:
    """Returns (opencv_ms_per_frame, detected_class_counts_per_frame). Only
    called when the caller has confirmed `yolo_model` loaded successfully."""
    from app.vision.pipeline import preprocess_for_detection

    _reset_and_apply_env(env)
    from app.vision.config import get_vision_config

    cfg = get_vision_config()
    opencv_ms: list[float] = []
    counts: list[dict[str, int]] = []
    for _, b in frames:
        result = preprocess_for_detection(b, camera_key, cfg)
        opencv_ms.append(result.opencv_ms)
        r = yolo_model.track(source=result.frame, persist=True, tracker="bytetrack.yaml", verbose=False)
        detected: dict[str, int] = {}
        if r:
            r0 = r[0]
            names = r0.names or {}
            if r0.boxes is not None:
                for box in r0.boxes:
                    cls_idx = int(box.cls[0]) if box.cls is not None else -1
                    cname = str(names.get(cls_idx, str(cls_idx)))
                    detected[cname] = detected.get(cname, 0) + 1
        counts.append(detected)
    return opencv_ms, counts


def _total_detections(counts: list[dict[str, int]]) -> int:
    return sum(sum(c.values()) for c in counts)


@dataclass
class ModuleResult:
    module_name: str
    enable_flag: str
    baseline_opencv_ms_mean: float
    module_opencv_ms_mean: float
    added_cost_ms: float
    added_cost_pct: float | None
    benefit_measured: bool
    benefit_reason: str
    detection_count_baseline: int | None = None
    detection_count_module: int | None = None
    detection_count_delta: int | None = None
    recommendation: str = ""
    recommended_default_state: str = ""


def _recommend(added_cost_ms: float, benefit_measured: bool, detection_delta: int | None) -> tuple[str, str]:
    """Returns (recommendation_text, recommended_default_state)."""
    if not benefit_measured:
        return (
            "Cost measured; benefit NOT measured (no YOLO detections available for this run). "
            "Per policy, a module is not recommended for default-on status without measurable "
            "benefit — keep OFF until run with --with-yolo against labeled or reviewed footage.",
            "OFF",
        )
    if detection_delta is not None and detection_delta > 0:
        if added_cost_ms <= 5.0:
            return (
                f"Measured detection improvement (+{detection_delta} detections) at low added cost "
                f"({added_cost_ms:.2f} ms/frame) — candidate for default ON, pending confirmation on "
                f"real (non-synthetic) footage.",
                "ON",
            )
        return (
            f"Measured detection improvement (+{detection_delta} detections) but added cost is "
            f"non-trivial ({added_cost_ms:.2f} ms/frame) — enable selectively (e.g. only on cameras "
            f"with known poor lighting) rather than globally.",
            "ON (selective)",
        )
    if detection_delta is not None and detection_delta <= 0:
        return (
            f"No positive detection improvement measured ({detection_delta:+d} detections) for "
            f"{added_cost_ms:.2f} ms/frame added cost — recommend OFF.",
            "OFF",
        )
    return ("Insufficient data to form a recommendation.", "OFF")


def evaluate_modules(
    frames: list[tuple[str, bytes]],
    *,
    camera_key: str = "eval-cam",
    with_yolo: bool = False,
    yolo_model=None,
    roi_yaml_path: str | None = None,
) -> list[ModuleResult]:
    """Runs Baseline once, then every module in OPENCV_MODULES once, all on
    the same `frames`. `yolo_model` must be a pre-loaded ultralytics YOLO
    instance (or None); this function never attempts to import/load
    ultralytics itself, so it works identically whether or not torch is
    installed in the current environment — the caller decides.
    """
    yolo_ready = with_yolo and yolo_model is not None

    if yolo_ready:
        baseline_opencv, baseline_counts = _run_with_yolo(frames, {}, camera_key, yolo_model)
        baseline_detections = _total_detections(baseline_counts)
    else:
        baseline_opencv = _run_opencv_only(frames, {}, camera_key)
        baseline_detections = None
    baseline_mean = round(statistics.mean(baseline_opencv), 4) if baseline_opencv else 0.0

    results: list[ModuleResult] = []
    for module in OPENCV_MODULES:
        env = {module.key: "true", **module.extra_env}
        if module.key == "ENABLE_ROI" and roi_yaml_path:
            env["ROI_CONFIG_PATH"] = roi_yaml_path

        if yolo_ready:
            mod_opencv, mod_counts = _run_with_yolo(frames, env, camera_key, yolo_model)
            mod_detections = _total_detections(mod_counts)
            detection_delta = mod_detections - baseline_detections
            benefit_measured = True
            benefit_reason = "Measured: real YOLO detections compared, same frames, baseline vs module-enabled."
        else:
            mod_opencv = _run_opencv_only(frames, env, camera_key)
            mod_detections = None
            detection_delta = None
            benefit_measured = False
            benefit_reason = (
                "Not measured: no loaded YOLO model was provided to this evaluation run "
                "(pass --with-yolo on an environment where ultralytics/torch are installed)."
            )

        mod_mean = round(statistics.mean(mod_opencv), 4) if mod_opencv else 0.0
        added_cost = round(mod_mean - baseline_mean, 4)
        added_pct = round(100.0 * added_cost / baseline_mean, 1) if baseline_mean > 0 else None

        recommendation, default_state = _recommend(added_cost, benefit_measured, detection_delta)

        results.append(
            ModuleResult(
                module_name=module.name,
                enable_flag=module.key,
                baseline_opencv_ms_mean=baseline_mean,
                module_opencv_ms_mean=mod_mean,
                added_cost_ms=added_cost,
                added_cost_pct=added_pct,
                benefit_measured=benefit_measured,
                benefit_reason=benefit_reason,
                detection_count_baseline=baseline_detections,
                detection_count_module=mod_detections,
                detection_count_delta=detection_delta,
                recommendation=recommendation,
                recommended_default_state=default_state,
            )
        )

    # Restore a clean environment so this function is safe to call
    # repeatedly (e.g. once per dataset) within one process.
    _reset_and_apply_env({})
    return results
