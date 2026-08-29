"""Publication-quality comparison charts across the 7 preprocessing
configurations. Each chart is generated ONLY if the underlying metric was
actually measured for at least one config in the run — a metric with no
data anywhere in `run.configs` produces no chart file rather than an empty
or fabricated one, and the caller (`evaluation/reporting/markdown_report.py`)
is expected to note the omission.
"""

from __future__ import annotations

from pathlib import Path

from evaluation.reporting.types import RunResult


def _bar_chart(labels: list[str], values: list[float], title: str, ylabel: str, out_path: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pairs = [(l, v) for l, v in zip(labels, values) if v is not None]
    if not pairs:
        return None
    labels, values = zip(*pairs)

    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    bars = ax.bar(range(len(labels)), values, color="#3b6fd6")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    for bar, v in zip(bars, values):
        ax.annotate(
            f"{v:.2f}" if isinstance(v, float) else str(v),
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=7,
        )
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# Each entry: (chart_filename_stem, chart_title, ylabel, extractor)
# extractor(config_run_result_as_dict) -> float | None
def _pipeline_metric_specs() -> list[tuple[str, str, str, callable]]:
    return [
        ("avg_fps", "Average FPS by Configuration", "FPS", lambda p: p.get("avg_fps")),
        ("cpu_percent", "CPU Usage by Configuration", "CPU %", lambda p: p.get("cpu_percent_avg")),
        ("memory_rss_mb", "Memory (RSS) by Configuration", "MB", lambda p: p.get("rss_mb_avg")),
        (
            "opencv_latency_ms",
            "OpenCV Stage Latency by Configuration",
            "ms (mean)",
            lambda p: (p.get("opencv_stage") or {}).get("mean_ms"),
        ),
        (
            "yolo_latency_ms",
            "YOLO Stage Latency by Configuration",
            "ms (mean)",
            lambda p: (p.get("yolo_stage") or {}).get("mean_ms"),
        ),
        (
            "total_pipeline_time_ms",
            "Total Pipeline Time by Configuration",
            "ms (mean)",
            lambda p: (p.get("total_stage") or {}).get("mean_ms"),
        ),
        (
            "frame_processing_time_ms",
            "Avg Frame Processing Time by Configuration",
            "ms/frame",
            lambda p: p.get("avg_processing_time_per_frame_ms"),
        ),
    ]


def _camera_quality_specs() -> list[tuple[str, str, str, callable]]:
    return [
        ("blur_score", "Blur Score by Configuration", "Variance of Laplacian", lambda q: q.get("blur_score_avg")),
        ("brightness", "Brightness by Configuration", "0-255", lambda q: q.get("brightness_avg")),
        ("camera_quality_score", "Overall Quality Score by Configuration", "0-1", lambda q: q.get("quality_score_avg")),
    ]


def generate_all_charts(run: RunResult, output_dir: str | Path) -> dict[str, str]:
    """Returns {chart_key: filepath} for every chart that had data. Callers
    should treat a missing key as "not generated because unmeasured", not
    an error."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, str] = {}

    config_names = [c.config_name for c in run.configs]

    for stem, title, ylabel, extractor in _pipeline_metric_specs():
        values = [extractor(c.pipeline) for c in run.configs]
        path = _bar_chart(config_names, values, title, ylabel, output_dir / f"{stem}_{run.run_id}.png")
        if path:
            generated[stem] = str(path)

    for stem, title, ylabel, extractor in _camera_quality_specs():
        values = [extractor(c.camera_quality) if c.camera_quality else None for c in run.configs]
        path = _bar_chart(config_names, values, title, ylabel, output_dir / f"{stem}_{run.run_id}.png")
        if path:
            generated[stem] = str(path)

    # Detection count / tracking count — only meaningful with real YOLO output.
    det_counts = [c.detection.get("detection_count") if c.detection else None for c in run.configs]
    path = _bar_chart(config_names, det_counts, "Detection Count by Configuration", "count", output_dir / f"detection_count_{run.run_id}.png")
    if path:
        generated["detection_count"] = str(path)

    track_counts = [c.tracking.get("unique_track_ids") if c.tracking else None for c in run.configs]
    path = _bar_chart(config_names, track_counts, "Unique Track Count by Configuration", "count", output_dir / f"tracking_count_{run.run_id}.png")
    if path:
        generated["tracking_count"] = str(path)

    return generated
