#!/usr/bin/env python3
"""Benchmark: OpenCV Integration Sprint — "before" vs "after" comparison.

"Before" = every vision/ ENABLE_* flag off (byte-for-byte the same code
path as pre-Sprint: decode only, no ROI/enhancement/quality). "After" =
a configurable set of flags on. Both configurations run through the exact
same `app.vision.pipeline.preprocess_for_detection()` entry point that
`person_tracker.track_frame()` calls in production.

Two ways to run this:

  1. In a sandbox / dev machine, without YOLO weights or real cameras:

       python scripts/benchmark_vision_pipeline.py --synthetic --iterations 200

     This measures the OpenCV stage only (decode/ROI/enhancement/quality) —
     honest about NOT including YOLO/ByteTrack time, since that needs real
     weights + (ideally) a GPU/real CPU load to mean anything.

  2. On the VPS / a machine with the real ai-engine dependencies and
     camera access, for real end-to-end numbers including YOLO+ByteTrack:

       python scripts/benchmark_vision_pipeline.py --images /path/to/sample_frames \\
           --with-yolo --iterations 100

     `--images` accepts a directory of jpg/png frames (e.g. saved from a
     real camera) instead of synthetic ones — more representative of
     actual store footage (lighting, motion blur, clutter) than the
     synthetic shapes `--synthetic` draws.

Either way, the script prints a comparison table and writes a JSON report
next to itself (`benchmark_report_<timestamp>.json`) with the raw numbers,
so results from a sandbox run and a VPS run can both be attached to the
Sprint report without being confused for each other (the JSON records
`"environment"` and whether `--with-yolo` was used).

This script only reads image files and calls into `app.vision` /
`app.services.person_tracker` — it does not touch the backend, the
database, or any camera/RTSP source directly.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402


def _log(msg: str) -> None:
    print(msg, flush=True)


def _make_synthetic_frames(n: int, size: tuple[int, int] = (720, 1280)) -> list[bytes]:
    """Generates n distinct, non-trivial synthetic frames (shapes + noise)
    encoded as JPEG bytes — used when no real sample images are supplied.
    Not a substitute for real footage; see module docstring."""
    import cv2

    height, width = size
    rng = np.random.default_rng(42)
    frames: list[bytes] = []
    for i in range(n):
        frame = np.full((height, width, 3), 40, dtype=np.uint8)
        cv2.rectangle(
            frame,
            (50 + (i * 7) % 200, 50),
            (250 + (i * 7) % 200, 250),
            (0, 180, 0),
            -1,
        )
        cv2.circle(frame, (width - 200, 150 + (i * 11) % 100), 60, (0, 0, 200), -1)
        noise = (rng.standard_normal((height, width, 3)) * 8).astype(np.int16)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        assert ok
        frames.append(buf.tobytes())
    return frames


def _load_image_frames(images_dir: Path) -> list[bytes]:
    exts = {".jpg", ".jpeg", ".png", ".bmp"}
    paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in exts)
    if not paths:
        raise SystemExit(f"No images found in {images_dir}")
    frames = []
    for p in paths:
        frames.append(p.read_bytes())
    return frames


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(len(values) * pct))
    return values[idx]


def _summarize(label: str, ms_values: list[float]) -> dict:
    return {
        "label": label,
        "count": len(ms_values),
        "mean_ms": round(statistics.mean(ms_values), 3) if ms_values else 0.0,
        "p50_ms": round(_percentile(ms_values, 0.50), 3),
        "p95_ms": round(_percentile(ms_values, 0.95), 3),
        "max_ms": round(max(ms_values), 3) if ms_values else 0.0,
        "fps_from_mean": round(1000.0 / statistics.mean(ms_values), 2)
        if ms_values and statistics.mean(ms_values) > 0
        else 0.0,
    }


def _try_start_resource_sampling():
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        proc.cpu_percent(interval=None)  # prime the internal counter
        return proc
    except ImportError:
        _log("(psutil not installed — skipping CPU/RAM measurement; "
             "`pip install psutil` to include it)")
        return None


def _sample_resources(proc) -> dict | None:
    if proc is None:
        return None
    import psutil  # already confirmed importable if proc is not None

    return {
        "cpu_percent": proc.cpu_percent(interval=None),
        "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
    }


def run_configuration(
    label: str,
    env_overrides: dict[str, str],
    frames: list[bytes],
    *,
    with_yolo: bool,
    camera_key: str,
) -> dict:
    # Clear every vision-related env var first so each configuration starts
    # from a clean slate (no leakage from a previous configuration in the
    # same process).
    from app.vision.config import VisionConfig, reload_vision_config

    known_flags = [f.upper() for f in vars(VisionConfig()).keys()]
    for name in list(os.environ.keys()):
        if any(name == flag or name.startswith("ENABLE_") for flag in known_flags):
            os.environ.pop(name, None)
    os.environ.update(env_overrides)
    cfg = reload_vision_config()

    from app.vision.metrics.timers import MetricsRegistry
    from app.vision.pipeline import preprocess_for_detection

    MetricsRegistry.reset()

    yolo_model = None
    if with_yolo:
        try:
            from ultralytics import YOLO

            yolo_model = YOLO(os.getenv("YOLO_MODEL", "yolov8n.pt"))
        except Exception as exc:  # noqa: BLE001
            _log(f"  (--with-yolo requested but YOLO unavailable: {exc}; "
                 "falling back to OpenCV-stage-only timing for this run)")
            yolo_model = None

    opencv_ms: list[float] = []
    yolo_ms: list[float] = []
    total_ms: list[float] = []
    low_quality_count = 0

    proc = _try_start_resource_sampling()
    resources_before = _sample_resources(proc)
    wall_start = time.perf_counter()

    for frame_bytes in frames:
        result = preprocess_for_detection(frame_bytes, camera_key, cfg)
        opencv_ms.append(result.opencv_ms)
        if result.quality is not None and result.quality.is_low_quality:
            low_quality_count += 1

        stage_yolo_ms = 0.0
        if yolo_model is not None:
            t0 = time.perf_counter()
            yolo_model.track(
                source=result.frame, persist=True, tracker="bytetrack.yaml", verbose=False
            )
            stage_yolo_ms = (time.perf_counter() - t0) * 1000.0
            yolo_ms.append(stage_yolo_ms)

        total_ms.append(result.opencv_ms + stage_yolo_ms)

    wall_elapsed_s = time.perf_counter() - wall_start
    resources_after = _sample_resources(proc)

    report = {
        "label": label,
        "env_overrides": env_overrides,
        "frame_count": len(frames),
        "wall_elapsed_s": round(wall_elapsed_s, 3),
        "wall_fps": round(len(frames) / wall_elapsed_s, 2) if wall_elapsed_s > 0 else 0.0,
        "opencv_stage": _summarize("opencv", opencv_ms),
        "yolo_bytetrack_stage": _summarize("yolo_bytetrack", yolo_ms) if yolo_ms else None,
        "total_stage": _summarize("total", total_ms),
        "low_quality_frames": low_quality_count,
        "resources": {"before": resources_before, "after": resources_after},
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=Path, default=None, help="Directory of sample frames (jpg/png)")
    parser.add_argument("--synthetic", action="store_true", help="Use generated synthetic frames instead")
    parser.add_argument("--iterations", type=int, default=100, help="Number of frames to process per configuration")
    parser.add_argument("--with-yolo", action="store_true", help="Also time the real YOLO+ByteTrack call (needs ultralytics + weights)")
    parser.add_argument("--camera-key", default="benchmark-cam", help="camera_key used for ROI lookup / metrics keying")
    parser.add_argument(
        "--after-flags",
        default="ENABLE_CLAHE=true,ENABLE_GAMMA=true,ENABLE_IMAGE_QUALITY=true,ENABLE_BLUR_ANALYSIS=true",
        help="Comma-separated KEY=VALUE env overrides for the 'after' configuration",
    )
    args = parser.parse_args()

    if args.images:
        frames = _load_image_frames(args.images)
        source_desc = f"images from {args.images}"
    else:
        frames = _make_synthetic_frames(args.iterations)
        source_desc = "synthetic generated frames (not real camera footage)"
    frames = (frames * ((args.iterations // len(frames)) + 1))[: args.iterations]

    after_overrides = {}
    for pair in args.after_flags.split(","):
        if not pair.strip():
            continue
        key, _, value = pair.partition("=")
        after_overrides[key.strip()] = value.strip()

    _log(f"Benchmarking with {len(frames)} frames ({source_desc})")
    _log(f"Python: {platform.python_version()}  Platform: {platform.platform()}")
    _log(f"--with-yolo: {args.with_yolo}\n")

    before_report = run_configuration(
        "before (all vision ENABLE_* off — pre-Sprint equivalent)",
        {},
        frames,
        with_yolo=args.with_yolo,
        camera_key=args.camera_key,
    )
    after_report = run_configuration(
        "after (" + args.after_flags + ")",
        after_overrides,
        frames,
        with_yolo=args.with_yolo,
        camera_key=args.camera_key,
    )

    def _fmt_stage(stage: dict | None) -> str:
        if stage is None:
            return "n/a"
        return f"mean={stage['mean_ms']}ms p95={stage['p95_ms']}ms fps~{stage['fps_from_mean']}"

    col1, col2, col3 = 22, 42, 42

    def _row(name: str, before_val: str, after_val: str) -> str:
        return f"{name:<{col1}}{before_val:<{col2}}{after_val:<{col3}}"

    _log("=" * (col1 + col2 + col3))
    _log(_row("metric", "BEFORE", "AFTER"))
    _log("-" * (col1 + col2 + col3))
    _log(_row("opencv stage", _fmt_stage(before_report["opencv_stage"]), _fmt_stage(after_report["opencv_stage"])))
    _log(_row("yolo+bytetrack stage", _fmt_stage(before_report["yolo_bytetrack_stage"]), _fmt_stage(after_report["yolo_bytetrack_stage"])))
    _log(_row("total stage", _fmt_stage(before_report["total_stage"]), _fmt_stage(after_report["total_stage"])))
    _log(_row("wall fps", str(before_report["wall_fps"]), str(after_report["wall_fps"])))
    _log(_row("low quality frames", str(before_report["low_quality_frames"]), str(after_report["low_quality_frames"])))
    if before_report["resources"]["after"]:
        b = before_report["resources"]["after"]
        a = after_report["resources"]["after"]
        _log(_row("cpu % (end of run)", str(b["cpu_percent"]), str(a["cpu_percent"])))
        _log(_row("rss MB (end of run)", str(b["rss_mb"]), str(a["rss_mb"])))
    _log("=" * (col1 + col2 + col3))

    out = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "with_yolo": args.with_yolo,
            "source": source_desc,
        },
        "before": before_report,
        "after": after_report,
    }
    out_path = Path(__file__).resolve().parent / f"benchmark_report_{int(time.time())}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    _log(f"\nFull JSON report written to: {out_path}")


if __name__ == "__main__":
    main()
