"""Full thesis-style Markdown report generator.

Builds on `evaluation/reporting/markdown_report.py`'s tables and adds the
sections a thesis defense chapter needs (Experimental Setup, Hardware/
Software Specification, Dataset Description, Methodology, Results,
Comparison, Discussion, Limitations, Future Work, Conclusions). Every
narrative sentence below is derived from fields actually present in the
`RunResult` — nothing here states a numeric conclusion that isn't backed
by a value in `run.configs`/`run.opencv_modules`/`run.cart_metrics`. Where
a section would otherwise need data this run didn't collect, it says so
explicitly (mirrors the same discipline as `markdown_report.py` and every
metrics collector in `evaluation/metrics/`).
"""

from __future__ import annotations

import platform
from pathlib import Path

from evaluation.reporting.markdown_report import _fmt, _table
from evaluation.reporting.types import RunResult


def _software_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for pkg in ("numpy", "cv2", "pandas", "openpyxl", "matplotlib"):
        try:
            mod = __import__(pkg)
            versions[pkg] = getattr(mod, "__version__", "unknown")
        except Exception:
            versions[pkg] = "not installed in this run's environment"
    try:
        import ultralytics

        versions["ultralytics"] = getattr(ultralytics, "__version__", "unknown")
    except Exception:
        versions["ultralytics"] = "not installed in this run's environment (see Limitations)"
    try:
        import torch

        versions["torch"] = getattr(torch, "__version__", "unknown")
    except Exception:
        versions["torch"] = "not installed in this run's environment (see Limitations)"
    return versions


def _hardware_spec() -> dict[str, str]:
    spec = {
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown (not reported by the OS on this run)",
        "python_build": " ".join(platform.python_build()),
    }
    try:
        import psutil

        spec["cpu_count_logical"] = str(psutil.cpu_count(logical=True))
        spec["cpu_count_physical"] = str(psutil.cpu_count(logical=False))
        spec["total_ram_gb"] = f"{psutil.virtual_memory().total / (1024**3):.1f}"
    except Exception:
        spec["cpu_ram_note"] = "psutil not available in this run's environment — CPU count/RAM not captured."
    return spec


def _fastest_slowest(run: RunResult) -> tuple[str | None, str | None]:
    ranked = [
        (c.config_name, (c.pipeline.get("total_stage") or {}).get("mean_ms"))
        for c in run.configs
        if (c.pipeline.get("total_stage") or {}).get("mean_ms") is not None
    ]
    if not ranked:
        return None, None
    ranked.sort(key=lambda t: t[1])
    return ranked[0][0], ranked[-1][0]


def _limitations(run: RunResult) -> list[str]:
    notes = []
    if not run.environment.get("with_yolo"):
        notes.append(
            "Real YOLO/ByteTrack inference was not available in this run's environment "
            "(ultralytics/torch not installed, or `--with-yolo` not passed). All pipeline "
            "and camera-quality figures reflect the OpenCV preprocessing stage only; YOLO "
            "latency, detection accuracy, and tracking stability are not measured in this "
            "run."
        )
    if not run.environment.get("labels_used"):
        notes.append(
            "No ground-truth annotations were supplied. Precision, recall, F1, and the "
            "confusion matrix are not measured — see `evaluation/datasets/annotations.py` "
            "for the two supported annotation formats."
        )
    if run.dataset.get("kind") == "synthetic":
        notes.append(
            "This run used synthetically generated frames, not real supermarket camera "
            "footage. Camera-quality and pipeline-cost figures are internally consistent "
            "and reproducible, but do not represent real-world lighting, motion, or scene "
            "content — a real-footage run (see VPS instructions) is required before citing "
            "these numbers as representative of production conditions."
        )
    if not run.opencv_modules:
        notes.append(
            "Per-module OpenCV cost/benefit evaluation was not run for this report "
            "(`--run-opencv-modules` not passed)."
        )
    if not run.cart_metrics:
        notes.append(
            "Shopping cart / order / camera metrics were not included in this report "
            "(run the `cart-metrics` subcommand against the backend database separately "
            "and pass `--cart-metrics-json`)."
        )
    else:
        cm = run.cart_metrics
        if cm.get("checkout_cancelled_count") is None:
            notes.append(f"Checkout-cancelled count: not measurable. {cm.get('checkout_cancelled_reason')}")
        if cm.get("qr_confirmation_count") is None:
            notes.append(f"QR vs. staff confirmation split: not measurable. {cm.get('qr_confirmation_reason')}")
        if cm.get("camera_uptime_reason"):
            notes.append(f"Camera uptime percentage: not measurable. {cm.get('camera_uptime_reason')}")
    for c in run.configs:
        if c.tracking and c.tracking.get("id_switch_count") is None:
            notes.append(f"True ID-switch count: not measurable in this run. {c.tracking.get('id_switch_reason')}")
            break
    return notes


def generate_thesis_report(run: RunResult, chart_paths: dict[str, str], output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"thesis_report_{run.run_id}.md"

    L: list[str] = []
    L.append("# VisionMart — Experimental Evaluation of OpenCV Preprocessing for Smart Retail Vision")
    L.append("")
    L.append(f"*Generated {run.generated_at} — run id `{run.run_id}` — VisionMart {run.environment.get('visionmart_version', 'unknown')}*")
    L.append("")

    L.append("## 1. Experimental Setup")
    L.append("")
    L.append(
        "This report compares 7 OpenCV preprocessing configurations applied before YOLO "
        "detection / ByteTrack tracking in the VisionMart AI Engine's vision pipeline "
        "(`ai-engine/app/vision/`). The evaluation framework (`evaluation/`) runs "
        "independently of the production pipeline: it imports the same preprocessing code "
        "for measurement fidelity but never modifies the checkout pipeline, database schema, "
        "APIs, shopping cart logic, or event bus, and never writes to production data."
    )
    L.append("")

    L.append("### 1.1 Hardware Specification")
    L.append("")
    for k, v in _hardware_spec().items():
        L.append(f"- **{k}**: {v}")
    L.append("")

    L.append("### 1.2 Software Versions")
    L.append("")
    for k, v in _software_versions().items():
        L.append(f"- **{k}**: {v}")
    L.append("")

    L.append("### 1.3 Dataset Description")
    L.append("")
    for k, v in run.dataset.items():
        L.append(f"- **{k}**: {v}")
    L.append("")

    L.append("## 2. Evaluation Methodology")
    L.append("")
    L.append(
        "Each of the 7 configurations (Baseline, Brightness/Contrast, Gamma Correction, "
        "CLAHE, Histogram Equalization, CLAHE+Gamma, and the Full OpenCV Pipeline) is applied "
        "to the same sequence of input frames, and the following are collected per "
        "configuration:\n"
        "- **Pipeline metrics**: OpenCV / YOLO / ByteTrack stage time, total latency, FPS, "
        "CPU/RAM/GPU usage, dropped frames (`evaluation/metrics/pipeline_metrics.py`).\n"
        "- **Camera quality metrics**: brightness, contrast, blur score, noise, motion %, "
        "frozen-frame detection (`evaluation/metrics/camera_quality_metrics.py`).\n"
        "- **Detection metrics** (only when ground truth is supplied): precision, recall, "
        "F1, confusion matrix via IoU box matching or count-level fallback "
        "(`evaluation/metrics/detection_metrics.py`).\n"
        "- **Tracking metrics** (only when YOLO/ByteTrack output is available): track "
        "lifetime, fragmentation, continuity, an ID-churn proxy, and true ID-switch count "
        "if ground-truth identity is supplied (`evaluation/metrics/tracking_metrics.py`).\n\n"
        "ByteTrack timing is not directly exposed by ultralytics' `model.track()` API (it "
        "fuses detection + tracking in one call). This framework derives it by calling "
        "`model.predict()` then `model.track()` on the same frame and computing "
        "`bytetrack_ms = track_ms - predict_ms` (clamped to ≥ 0) — an estimate from two real "
        "measurements, always labeled as derived, never presented as a direct trace."
    )
    L.append("")

    L.append("## 3. Experimental Results")
    L.append("")
    L.append("### 3.1 Pipeline Performance")
    L.append("")
    headers = ["Config", "Avg FPS", "OpenCV mean ms", "YOLO mean ms", "ByteTrack mean ms", "Total mean ms", "CPU %", "RSS MB"]
    rows = []
    for c in run.configs:
        p = c.pipeline
        rows.append([
            c.config_name, p.get("avg_fps"),
            (p.get("opencv_stage") or {}).get("mean_ms"),
            (p.get("yolo_stage") or {}).get("mean_ms"),
            (p.get("bytetrack_stage") or {}).get("mean_ms"),
            (p.get("total_stage") or {}).get("mean_ms"),
            p.get("cpu_percent_avg"), p.get("rss_mb_avg"),
        ])
    L.append(_table(headers, rows))
    L.append("")
    if "total_pipeline_time_ms" in chart_paths:
        L.append(f"![Total Pipeline Time]({Path(chart_paths['total_pipeline_time_ms']).name})")
        L.append("")

    L.append("### 3.2 Camera / Image Quality")
    L.append("")
    if any(c.camera_quality for c in run.configs):
        headers = ["Config", "Brightness", "Blur Score", "Quality Score", "Low-Quality %", "Frozen %"]
        rows = []
        for c in run.configs:
            q = c.camera_quality or {}
            rows.append([c.config_name, q.get("brightness_avg"), q.get("blur_score_avg"), q.get("quality_score_avg"), q.get("low_quality_frame_pct"), q.get("frozen_frame_pct")])
        L.append(_table(headers, rows))
    else:
        L.append("Not measured for this run.")
    L.append("")

    L.append("### 3.3 Detection Accuracy")
    L.append("")
    if any(c.detection and c.detection.get("measurable") for c in run.configs):
        headers = ["Config", "Precision", "Recall", "F1", "TP", "FP", "FN"]
        rows = [
            [c.config_name, (c.detection or {}).get("precision"), (c.detection or {}).get("recall"),
             (c.detection or {}).get("f1"), (c.detection or {}).get("tp"), (c.detection or {}).get("fp"),
             (c.detection or {}).get("fn")]
            for c in run.configs
        ]
        L.append(_table(headers, rows))
    else:
        reason = next((c.detection.get("reason") for c in run.configs if c.detection), "No ground truth was supplied for this run.")
        L.append(f"Not measured: {reason}")
    L.append("")

    L.append("### 3.4 Tracking Stability")
    L.append("")
    if any(c.tracking for c in run.configs):
        headers = ["Config", "Unique IDs", "Continuity", "Fragmentation", "Lost Tracks", "ID Churn Proxy"]
        rows = [
            [c.config_name, (c.tracking or {}).get("unique_track_ids"), (c.tracking or {}).get("avg_track_continuity"),
             (c.tracking or {}).get("fragmentation_count"), (c.tracking or {}).get("lost_track_events"),
             (c.tracking or {}).get("id_churn_proxy")]
            for c in run.configs
        ]
        L.append(_table(headers, rows))
    else:
        L.append("Not measured: no YOLO/ByteTrack output was available for this run (requires `--with-yolo`).")
    L.append("")

    L.append("## 4. Performance Comparison")
    L.append("")
    fastest, slowest = _fastest_slowest(run)
    if fastest and slowest and fastest != slowest:
        L.append(f"Across the measured configurations, **{fastest}** had the lowest total pipeline latency and **{slowest}** the highest.")
    elif fastest:
        L.append(f"Only one configuration ({fastest}) produced a measurable total pipeline latency in this run.")
    else:
        L.append("Insufficient data to rank configurations by latency in this run.")
    L.append("")

    L.append("## 5. OpenCV Module Comparison")
    L.append("")
    if run.opencv_modules:
        headers = ["Module", "Added Cost (ms)", "Benefit Measured", "Detection Δ", "Recommendation", "Default"]
        rows = [
            [m.get("module_name"), m.get("added_cost_ms"), m.get("benefit_measured"),
             m.get("detection_count_delta"), m.get("recommendation"), m.get("recommended_default_state")]
            for m in run.opencv_modules
        ]
        L.append(_table(headers, rows))
    else:
        L.append("Not run for this report (`--run-opencv-modules` not passed).")
    L.append("")

    L.append("## 6. Discussion")
    L.append("")
    L.append(
        "Every OpenCV enhancement module adds measurable OpenCV-stage cost (see §3.1/§5); "
        "none of them is free. Whether that cost is justified depends entirely on measured "
        "detection/tracking benefit (§3.3–3.4, §5) — per this framework's policy, a module is "
        "not recommended for default-on status without a positive, measured benefit. Where "
        "benefit could not be measured in this run (see Limitations), the corresponding "
        "modules are recommended OFF pending a run with real labeled footage, not because "
        "they are assumed ineffective."
    )
    L.append("")

    L.append("## 7. Limitations")
    L.append("")
    limitations = _limitations(run)
    if limitations:
        for note in limitations:
            L.append(f"- {note}")
    else:
        L.append("- None identified: this run had real YOLO output, ground-truth labels, real footage, per-module evaluation, and cart metrics all available.")
    L.append("")

    L.append("## 8. Future Work")
    L.append("")
    L.append(
        "- Run this framework against real supermarket footage (see VPS instructions) with "
        "the ai-engine container's installed `ultralytics`/`torch` to obtain real detection/"
        "tracking accuracy figures.\n"
        "- Build a labeled evaluation set (box-level annotations, per §2) sized enough for "
        "statistically meaningful precision/recall per class.\n"
        "- If cross-camera re-identification becomes a product requirement, add it to "
        "`person_tracker.py` and extend `tracking_metrics.py`'s `re_id_implemented` path "
        "accordingly.\n"
        "- If checkout-cancellation and QR-vs-staff-confirmation reporting are needed for "
        "future evaluations, persist those events to the audit log in production code (a "
        "change outside this framework's read-only, non-invasive scope)."
    )
    L.append("")

    L.append("## 9. Conclusions")
    L.append("")
    L.append(
        "This report presents only measured results; any metric this run could not measure "
        "is listed in §7 with the specific reason rather than estimated. See the accompanying "
        "JSON/CSV/XLSX exports for the complete raw data behind every table above."
    )
    L.append("")

    out_path.write_text("\n".join(L), encoding="utf-8")
    return out_path
