"""Markdown summary report: comparison tables + embedded charts + explicit
notes on what was and wasn't measured. This is the per-run summary, not
the full thesis-style report (see `evaluation/reporting/thesis_report.py`
for Experimental Setup / Discussion / Limitations / Conclusions sections,
which additionally consumes this module's tables).
"""

from __future__ import annotations

from pathlib import Path

from evaluation.reporting.types import RunResult


def _fmt(v) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def _table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(v) for v in row) + " |")
    return "\n".join(lines)


def generate_markdown_report(
    run: RunResult,
    chart_paths: dict[str, str],
    output_dir: str | Path,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"evaluation_report_{run.run_id}.md"

    lines: list[str] = []
    lines.append(f"# VisionMart Experimental Evaluation Report — {run.run_id}")
    lines.append("")
    lines.append(f"Generated: {run.generated_at}")
    lines.append("")
    lines.append("## Environment")
    lines.append("")
    for k, v in run.environment.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Dataset")
    lines.append("")
    for k, v in run.dataset.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")

    if not run.environment.get("with_yolo"):
        lines.append(
            "> **Note:** this run did not include real YOLO inference "
            "(`with_yolo=False`). Pipeline/camera-quality metrics below reflect "
            "the OpenCV preprocessing stage only. Detection and tracking metrics "
            "are reported as not measured for this run."
        )
        lines.append("")

    # --- Pipeline metrics table ---
    lines.append("## Pipeline Performance Comparison")
    lines.append("")
    headers = ["Config", "Avg FPS", "OpenCV mean ms", "YOLO mean ms", "Total mean ms", "CPU %", "RSS MB", "Dropped Frames"]
    rows = []
    for c in run.configs:
        p = c.pipeline
        rows.append([
            c.config_name,
            p.get("avg_fps"),
            (p.get("opencv_stage") or {}).get("mean_ms"),
            (p.get("yolo_stage") or {}).get("mean_ms"),
            (p.get("total_stage") or {}).get("mean_ms"),
            p.get("cpu_percent_avg"),
            p.get("rss_mb_avg"),
            p.get("dropped_frames"),
        ])
    lines.append(_table(headers, rows))
    lines.append("")
    if "avg_fps" in chart_paths:
        lines.append(f"![Average FPS]({Path(chart_paths['avg_fps']).name})")
        lines.append("")
    if "total_pipeline_time_ms" in chart_paths:
        lines.append(f"![Total Pipeline Time]({Path(chart_paths['total_pipeline_time_ms']).name})")
        lines.append("")

    # --- Camera quality table ---
    if any(c.camera_quality for c in run.configs):
        lines.append("## Camera / Image Quality Comparison")
        lines.append("")
        headers = ["Config", "Brightness", "Contrast", "Blur Score", "Quality Score", "Low-Quality %"]
        rows = []
        for c in run.configs:
            q = c.camera_quality or {}
            rows.append([
                c.config_name, q.get("brightness_avg"), q.get("contrast_avg"),
                q.get("blur_score_avg"), q.get("quality_score_avg"), q.get("low_quality_frame_pct"),
            ])
        lines.append(_table(headers, rows))
        lines.append("")
        if "blur_score" in chart_paths:
            lines.append(f"![Blur Score]({Path(chart_paths['blur_score']).name})")
            lines.append("")

    # --- Detection metrics ---
    lines.append("## Detection Accuracy Comparison")
    lines.append("")
    if any(c.detection and c.detection.get("measurable") for c in run.configs):
        headers = ["Config", "Precision", "Recall", "F1", "TP", "FP", "FN", "Avg Confidence"]
        rows = []
        for c in run.configs:
            d = c.detection or {}
            rows.append([c.config_name, d.get("precision"), d.get("recall"), d.get("f1"), d.get("tp"), d.get("fp"), d.get("fn"), d.get("avg_confidence")])
        lines.append(_table(headers, rows))
    else:
        reason = next((c.detection.get("reason") for c in run.configs if c.detection), "No ground-truth labels or YOLO output were available for this run.")
        lines.append(f"**Not measured.** {reason}")
    lines.append("")

    # --- Tracking metrics ---
    lines.append("## Tracking Stability Comparison")
    lines.append("")
    if any(c.tracking for c in run.configs):
        headers = ["Config", "Unique IDs", "Avg Track Length", "Continuity", "Fragmentation", "Lost Tracks", "ID Churn Proxy"]
        rows = []
        for c in run.configs:
            t = c.tracking or {}
            rows.append([
                c.config_name, t.get("unique_track_ids"), t.get("avg_track_length_frames"),
                t.get("avg_track_continuity"), t.get("fragmentation_count"),
                t.get("lost_track_events"), t.get("id_churn_proxy"),
            ])
        lines.append(_table(headers, rows))
        first_reason = next((c.tracking.get("id_switch_reason") for c in run.configs if c.tracking), None)
        if first_reason:
            lines.append("")
            lines.append(f"> True ID-switch count: {first_reason}")
    else:
        lines.append("**Not measured.** This run produced no ByteTrack ID sequences (requires `--with-yolo` on a video/RTSP dataset).")
    lines.append("")

    # --- OpenCV per-module evaluation ---
    if run.opencv_modules:
        lines.append("## OpenCV Module Cost / Benefit Evaluation")
        lines.append("")
        headers = ["Module", "Added Cost (ms)", "Added Cost (%)", "Benefit Measured", "Detection Δ", "Recommendation", "Default"]
        rows = []
        for m in run.opencv_modules:
            rows.append([
                m.get("module_name"), m.get("added_cost_ms"), m.get("added_cost_pct"),
                m.get("benefit_measured"), m.get("detection_count_delta"),
                m.get("recommendation"), m.get("recommended_default_state"),
            ])
        lines.append(_table(headers, rows))
        lines.append("")

    # --- Cart / order metrics ---
    if run.cart_metrics:
        cm = run.cart_metrics
        lines.append("## Shopping Cart / Order Metrics (Read-Only DB Snapshot)")
        lines.append("")
        lines.append(f"- Window: {cm.get('window_start')} → {cm.get('window_end')}")
        lines.append(f"- Total carts: {cm.get('cart_count_total')} — by status: {cm.get('cart_count_by_status')}")
        lines.append(f"- Converted carts: {cm.get('converted_count')}, avg completion time: {_fmt(cm.get('avg_cart_completion_seconds'))} s")
        lines.append(f"- Products detected (cart line entries) total: {cm.get('products_detected_total')}, avg per converted cart: {_fmt(cm.get('avg_products_per_converted_cart'))}")
        lines.append(f"- Customer association rate: {_fmt(cm.get('customer_association_rate'))}")
        lines.append(f"- Orders: {cm.get('order_count')} — by status: {cm.get('order_status_counts')}, avg total: {_fmt(cm.get('avg_order_total_amount'))}")
        lines.append(f"- Cameras online now: {cm.get('camera_online_now_count')}/{cm.get('camera_total_count')}")
        lines.append("")
        lines.append(f"> Checkout-cancelled count: **not measured** — {cm.get('checkout_cancelled_reason')}")
        lines.append("")
        lines.append(f"> QR vs staff confirmation split: **not measured** — {cm.get('qr_confirmation_reason')}")
        lines.append("")
        lines.append(f"> Camera uptime %: **not measured** — {cm.get('camera_uptime_reason')}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
