#!/usr/bin/env python3
"""Command-line entrypoint for the VisionMart Experimental Evaluation
Framework.

Subcommands
-----------
evaluate       Run the 7-config OpenCV preprocessing comparison (+ optional
               per-module cost/benefit evaluation) over a dataset (image
               folder, video file, RTSP recording, or camera recording),
               then export CSV/XLSX/JSON/Markdown + a thesis-style report.
cart-metrics   Read-only Shopping Cart / Order / Camera metrics from the
               backend's Postgres database. MUST be run as a separate
               process from `evaluate` — see the module docstring in
               `evaluation/cart/cart_metrics.py` for why (both services
               define an unrelated top-level `app` package).
thesis-report  Regenerate the full thesis-style report from a previously
               exported `evaluate` JSON file (and, optionally, a
               previously exported `cart-metrics` JSON file).

Examples
--------
Image folder, cost-only (no YOLO, no labels):
    python -m evaluation.cli evaluate --input-kind images --input /data/frames

Image folder with ground truth, real YOLO (run where ultralytics/torch are
installed — e.g. the ai-engine container/VPS):
    python -m evaluation.cli evaluate --input-kind images --input /data/frames \\
        --with-yolo --labels /data/labels.json --run-opencv-modules

Video file (also the right mode for a saved RTSP or camera recording):
    python -m evaluation.cli evaluate --input-kind video --input /data/store_cam1.mp4 \\
        --with-yolo --sample-every-n-frames 3

Live RTSP stream (no prior recording) — pass the URL directly:
    python -m evaluation.cli evaluate --input-kind rtsp --input rtsp://192.168.1.50/stream1 \\
        --with-yolo --max-frames 600

Cart/order metrics, run on the VPS where the backend's DATABASE_URL is reachable:
    python -m evaluation.cli cart-metrics --database-url postgresql+asyncpg://... \\
        --output-dir ./evaluation_results

Merge a previously produced cart-metrics JSON into a thesis report:
    python -m evaluation.cli evaluate --input-kind images --input /data/frames \\
        --cart-metrics-json ./evaluation_results/cart_metrics_20260704_120000.json

Quick sandbox smoke test (synthetic frames, no real footage — for CI / wiring
verification only, NEVER cited as a real accuracy result):
    python -m evaluation.cli evaluate --synthetic-frames 40
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai-engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_file_logger = None  # set by main() once --output-dir is known; see logging_config.py


def _log(msg: str = "") -> None:
    print(msg, flush=True)
    if _file_logger is not None:
        _file_logger.info(msg)


def _make_synthetic_frames(n: int) -> list[tuple[str, bytes]]:
    import cv2
    import numpy as np

    rng = np.random.default_rng(42)
    out = []
    for i in range(n):
        img = rng.integers(30, 100, size=(240, 320, 3), dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        out.append((f"synthetic_{i:04d}.jpg", buf.tobytes()))
    return out


def _apply_vision_env(env: dict[str, str]):
    from app.vision.config import VisionConfig, reload_vision_config

    known_flags = [k.upper() for k in vars(VisionConfig()).keys()]
    for k in list(os.environ.keys()):
        if k.startswith("ENABLE_") or k in known_flags:
            os.environ.pop(k, None)
    os.environ.update(env)
    return reload_vision_config()


def _extract_detections_and_ids(track_result) -> tuple[list, set[int]]:
    from evaluation.metrics.detection_metrics import Detection

    detections: list[Detection] = []
    track_ids: set[int] = set()
    if not track_result:
        return detections, track_ids
    r0 = track_result[0]
    names = r0.names or {}
    if r0.boxes is not None:
        for box in r0.boxes:
            cls_idx = int(box.cls[0]) if box.cls is not None else -1
            cname = str(names.get(cls_idx, str(cls_idx)))
            conf = float(box.conf[0]) if box.conf is not None else None
            bbox = tuple(float(x) for x in box.xyxy[0].tolist()) if box.xyxy is not None else None
            detections.append(Detection(class_name=cname, bbox=bbox, confidence=conf))
            if box.id is not None:
                track_ids.add(int(box.id[0]))
    return detections, track_ids


def cmd_evaluate(args: argparse.Namespace) -> None:
    from evaluation.config import PREPROCESSING_CONFIGS
    from evaluation.datasets import load_annotations, load_dataset
    from evaluation.metrics.camera_quality_metrics import CameraQualityCollector
    from evaluation.metrics.detection_metrics import DetectionMetricsCollector
    from evaluation.metrics.opencv_module_eval import evaluate_modules
    from evaluation.metrics.pipeline_metrics import PipelineMetricsCollector
    from evaluation.metrics.tracking_metrics import TrackingMetricsCollector
    from evaluation.reporting.charts import generate_all_charts
    from evaluation.reporting.exporters import export_csv, export_json, export_xlsx
    from evaluation.reporting.markdown_report import generate_markdown_report
    from evaluation.reporting.thesis_report import generate_thesis_report
    from evaluation.reporting.types import (
        ConfigRunResult,
        RunResult,
        default_environment,
        new_run_id,
        to_plain,
    )

    from app.vision.pipeline import preprocess_for_detection

    dropped_frames = 0
    if args.synthetic_frames:
        frames = _make_synthetic_frames(args.synthetic_frames)
        dataset_info = {
            "kind": "synthetic",
            "path": None,
            "frame_count": len(frames),
            "source_description": (
                "SYNTHETIC generated frames — NOT real camera footage. For CI / "
                "wiring verification only; do not cite these numbers as real "
                "detection/quality results in the thesis."
            ),
        }
    else:
        if not args.input_kind or not args.input:
            _log("ERROR: --input-kind and --input are required unless --synthetic-frames is given.")
            sys.exit(2)
        dataset = load_dataset(
            args.input_kind, args.input,
            sample_every_n_frames=args.sample_every_n_frames, max_frames=args.max_frames,
        )
        frame_objs = list(dataset)
        frames = [(f.name, f.image_bytes) for f in frame_objs]
        dropped_frames = getattr(dataset, "dropped_frames", 0)
        dataset_info = {
            "kind": args.input_kind, "path": str(args.input),
            "frame_count": len(frames), "dropped_frames": dropped_frames,
            "source_description": f"{args.input_kind} dataset at {args.input}",
        }

    labels = load_annotations(args.labels) if args.labels else None

    yolo_model = None
    if args.with_yolo:
        try:
            from ultralytics import YOLO

            yolo_model = YOLO(args.yolo_model)
        except Exception as exc:  # noqa: BLE001
            _log(f"WARNING: --with-yolo requested but unavailable here ({exc}). "
                 f"Detection/tracking metrics will be reported as not measured.")

    roi_yaml_path = args.roi_yaml
    if roi_yaml_path is None and any(c.env.get("ENABLE_ROI") == "true" for c in PREPROCESSING_CONFIGS):
        roi_yaml_path = str(Path(args.output_dir) / "_eval_roi.yaml")
        Path(roi_yaml_path).parent.mkdir(parents=True, exist_ok=True)
        Path(roi_yaml_path).write_text(
            "cameras:\n"
            f"  {args.camera_key}:\n"
            "    zones:\n"
            "      - name: checkout\n        type: checkout\n"
            "        points: [[0.5,0.0],[1.0,0.0],[1.0,1.0],[0.5,1.0]]\n",
            encoding="utf-8",
        )

    config_results: list[ConfigRunResult] = []
    for pc in PREPROCESSING_CONFIGS:
        env = dict(pc.env)
        if env.get("ENABLE_ROI") == "true" and "ROI_CONFIG_PATH" not in env and roi_yaml_path:
            env["ROI_CONFIG_PATH"] = roi_yaml_path
        vcfg = _apply_vision_env(env)

        pmc = PipelineMetricsCollector(pc.name)
        cqc = CameraQualityCollector()
        dmc = DetectionMetricsCollector(labels) if labels is not None else None
        tmc = TrackingMetricsCollector() if yolo_model is not None else None

        _log(f"Running config {pc.id}. {pc.name} ({len(frames)} frames)...")
        pmc.start()
        for i, (name, frame_bytes) in enumerate(frames):
            result = preprocess_for_detection(frame_bytes, args.camera_key, vcfg)

            yolo_ms = None
            bytetrack_ms = None
            if yolo_model is not None:
                t0 = time.perf_counter()
                pred = yolo_model.predict(source=result.frame, verbose=False)
                yolo_ms = (time.perf_counter() - t0) * 1000.0
                t1 = time.perf_counter()
                trk = yolo_model.track(source=result.frame, persist=True, tracker="bytetrack.yaml", verbose=False)
                track_ms = (time.perf_counter() - t1) * 1000.0
                bytetrack_ms = max(0.0, track_ms - yolo_ms)
                detections, track_ids = _extract_detections_and_ids(trk)
                if dmc is not None:
                    dmc.add_frame(name, detections)
                if tmc is not None:
                    tmc.observe(i, track_ids)

            pmc.record(name, opencv_ms=result.opencv_ms, yolo_ms=yolo_ms, bytetrack_ms=bytetrack_ms)
            cqc.observe(name, result.frame)
        pmc.stop()
        pmc.dropped_frames = dropped_frames

        config_results.append(
            ConfigRunResult(
                config_id=pc.id,
                config_name=pc.name,
                pipeline=pmc.summary(),
                camera_quality=cqc.summary(),
                detection=to_plain(dmc.summary()) if dmc is not None else None,
                tracking=to_plain(tmc.summary()) if tmc is not None else None,
            )
        )

    opencv_modules = None
    if args.run_opencv_modules:
        _log("Running per-module OpenCV cost/benefit evaluation...")
        opencv_modules = to_plain(
            evaluate_modules(
                frames, camera_key=args.camera_key,
                with_yolo=yolo_model is not None, yolo_model=yolo_model,
                roi_yaml_path=roi_yaml_path,
            )
        )

    cart_metrics = None
    if args.cart_metrics_json:
        cart_metrics = json.loads(Path(args.cart_metrics_json).read_text(encoding="utf-8"))

    run = RunResult(
        run_id=new_run_id(),
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        dataset=dataset_info,
        environment=default_environment(
            with_yolo=yolo_model is not None,
            labels_used=str(args.labels) if args.labels else None,
        ),
        configs=config_results,
        opencv_modules=opencv_modules,
        cart_metrics=cart_metrics,
    )

    output_dir = Path(args.output_dir)
    json_path = export_json(run, output_dir)
    csv_paths = export_csv(run, output_dir)
    xlsx_path = export_xlsx(run, output_dir)
    chart_paths = generate_all_charts(run, output_dir)
    md_path = generate_markdown_report(run, chart_paths, output_dir)
    thesis_path = None
    if not args.skip_thesis_report:
        thesis_path = generate_thesis_report(run, chart_paths, output_dir)

    _log("\n=== Evaluation complete ===")
    _log(f"JSON report:      {json_path}")
    for p in csv_paths:
        _log(f"CSV table:        {p}")
    _log(f"Excel workbook:   {xlsx_path}")
    for name in chart_paths:
        _log(f"Chart:            {chart_paths[name]}")
    _log(f"Markdown summary: {md_path}")
    if thesis_path:
        _log(f"Thesis report:    {thesis_path}")
    if not yolo_model:
        _log(
            "\nNOTE: --with-yolo not set (or ultralytics/torch unavailable here) — "
            "detection/tracking metrics were not measured for this run."
        )
    if labels is None:
        _log("NOTE: --labels not given — detection precision/recall/F1 were not measured.")


def cmd_cart_metrics(args: argparse.Namespace) -> None:
    from evaluation.cart.cart_metrics import collect_cart_metrics
    from evaluation.reporting.types import to_plain

    window_start = _parse_dt(args.window_start)
    window_end = _parse_dt(args.window_end)

    result = asyncio.run(
        collect_cart_metrics(
            args.database_url,
            organization_id=args.organization_id,
            window_start=window_start,
            window_end=window_end,
        )
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"cart_metrics_{run_id}.json"
    out_path.write_text(json.dumps(to_plain(result), indent=2, default=str), encoding="utf-8")
    _log(f"Cart metrics written to: {out_path}")
    _log("Pass this file to `evaluate --cart-metrics-json <path>` to include it in a report.")


def _parse_dt(value: str | None):
    if not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value)


def cmd_thesis_report(args: argparse.Namespace) -> None:
    from evaluation.reporting.thesis_report import generate_thesis_report
    from evaluation.reporting.types import ConfigRunResult, RunResult

    data = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
    if args.cart_metrics_json:
        data["cart_metrics"] = json.loads(Path(args.cart_metrics_json).read_text(encoding="utf-8"))

    run = RunResult(
        run_id=data["run_id"], generated_at=data["generated_at"],
        dataset=data["dataset"], environment=data["environment"],
        configs=[ConfigRunResult(**c) for c in data["configs"]],
        opencv_modules=data.get("opencv_modules"), cart_metrics=data.get("cart_metrics"),
    )
    output_dir = Path(args.output_dir)
    path = generate_thesis_report(run, {}, output_dir)
    _log(f"Thesis report written to: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("evaluate", help="Run the 7-config comparison over a dataset.")
    p_eval.add_argument("--input-kind", choices=["images", "video", "rtsp", "camera"])
    p_eval.add_argument("--input", help="Path to an image folder, video file, or RTSP/camera URL/recording.")
    p_eval.add_argument("--sample-every-n-frames", type=int, default=1)
    p_eval.add_argument("--max-frames", type=int, default=None)
    p_eval.add_argument("--synthetic-frames", type=int, default=0, help="Sandbox/CI smoke-test mode; not a real dataset.")
    p_eval.add_argument("--with-yolo", action="store_true")
    p_eval.add_argument("--yolo-model", default="yolov8n.pt")
    p_eval.add_argument("--labels", default=None, help="Ground-truth JSON — see evaluation/datasets/annotations.py")
    p_eval.add_argument("--roi-yaml", default=None)
    p_eval.add_argument("--camera-key", default="eval-cam")
    p_eval.add_argument("--run-opencv-modules", action="store_true")
    p_eval.add_argument("--cart-metrics-json", default=None, help="Pre-computed output of the `cart-metrics` subcommand.")
    p_eval.add_argument("--output-dir", default="./evaluation_results")
    p_eval.add_argument("--skip-thesis-report", action="store_true")
    p_eval.set_defaults(func=cmd_evaluate)

    p_cart = sub.add_parser("cart-metrics", help="Read-only cart/order/camera DB metrics (run as a separate process).")
    p_cart.add_argument("--database-url", required=True)
    p_cart.add_argument("--organization-id", default=None)
    p_cart.add_argument("--window-start", default=None, help="ISO 8601, e.g. 2026-07-01T00:00:00")
    p_cart.add_argument("--window-end", default=None)
    p_cart.add_argument("--output-dir", default="./evaluation_results")
    p_cart.set_defaults(func=cmd_cart_metrics)

    p_thesis = sub.add_parser("thesis-report", help="Regenerate the thesis report from a previous evaluate run.")
    p_thesis.add_argument("--run-json", required=True)
    p_thesis.add_argument("--cart-metrics-json", default=None)
    p_thesis.add_argument("--output-dir", default="./evaluation_results")
    p_thesis.set_defaults(func=cmd_thesis_report)

    args = parser.parse_args()

    global _file_logger
    try:
        from evaluation.logging_config import configure_logging

        _file_logger = configure_logging(args.output_dir)
    except Exception:  # noqa: BLE001 — file logging is a nice-to-have, never block a run over it
        _file_logger = None

    args.func(args)


if __name__ == "__main__":
    main()
