#!/usr/bin/env python3
"""Sprint 1 quantitative evaluation — the 7-configuration comparison
requested before starting Sprint 2:

  1. Baseline (no preprocessing)
  2. Brightness/Contrast only
  3. CLAHE only
  4. Histogram Equalization only
  5. Gamma Correction only
  6. CLAHE + Gamma
  7. Full preprocessing pipeline

What this script measures for real, in any environment with this repo's
`ai-engine` dependencies installed: OpenCV preprocessing stage time (mean/
p95), FPS of that stage, CPU%, and RSS memory (via psutil, optional).

What it does NOT measure, and will not fabricate:
  - YOLO inference time / total pipeline latency — needs `ultralytics` +
    `torch` actually importable. Pass `--with-yolo` to include this *if*
    those are installed in the environment you're running in (they are on
    the deployed ai-engine container/VPS per its Dockerfile; they are not
    installed in a typical bare dev sandbox because the CPU torch wheel
    alone is ~500MB).
  - Detection precision / recall / false positives / false negatives /
    tracking stability / customer count / product count — these require
    labeled ground truth on real footage (who/what was actually in frame,
    frame by frame) or at minimum real camera footage with a human
    reviewing YOLO's output. Pass `--images <dir> --labels <coco_or_simple_json>`
    once such a dataset exists; without `--labels`, this script only
    reports raw detection *counts* per class (no precision/recall/FP/FN),
    which is explicitly weaker evidence and labeled as such in the output.

Usage:
    # Cost-only comparison (works anywhere, no YOLO needed):
    python scripts/sprint1_evaluation.py --synthetic --iterations 150

    # Full comparison including real YOLO+ByteTrack (run where ultralytics
    # + torch are installed — e.g. inside the ai-engine container/VPS):
    python scripts/sprint1_evaluation.py --images /path/to/real_frames --with-yolo

    # With ground-truth labels for precision/recall/FP/FN (simple format,
    # see `_load_labels` docstring):
    python scripts/sprint1_evaluation.py --images /path/to/real_frames --with-yolo \\
        --labels /path/to/labels.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402


def _log(msg: str = "") -> None:
    print(msg, flush=True)


CONFIGS: list[tuple[str, dict[str, str]]] = [
    ("1. Baseline (no preprocessing)", {}),
    (
        "2. Brightness/Contrast only",
        {
            "ENABLE_BRIGHTNESS_ADJUST": "true", "BRIGHTNESS_DELTA": "15",
            "ENABLE_CONTRAST_ADJUST": "true", "CONTRAST_ALPHA": "1.2",
        },
    ),
    ("3. CLAHE only", {"ENABLE_CLAHE": "true"}),
    ("4. Histogram Equalization only", {"ENABLE_HIST_EQ": "true"}),
    ("5. Gamma Correction only", {"ENABLE_GAMMA": "true", "GAMMA_VALUE": "1.5"}),
    (
        "6. CLAHE + Gamma",
        {"ENABLE_CLAHE": "true", "ENABLE_GAMMA": "true", "GAMMA_VALUE": "1.5"},
    ),
    (
        "7. Full preprocessing pipeline",
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
    ),
]


def _make_synthetic_frames(n: int) -> list[bytes]:
    import cv2

    rng = np.random.default_rng(2026)
    frames = []
    for i in range(n):
        frame = np.full((720, 1280, 3), 35, dtype=np.uint8)
        cv2.rectangle(frame, (50 + (i * 7) % 200, 50), (250 + (i * 7) % 200, 250), (0, 170, 0), -1)
        cv2.circle(frame, (1000, 150 + (i * 11) % 100), 60, (0, 0, 190), -1)
        cv2.rectangle(frame, (600, 400), (750, 550), (150, 150, 0), -1)
        noise = (rng.standard_normal((720, 1280, 3)) * 9).astype(np.int16)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        assert ok
        frames.append(buf.tobytes())
    return frames


def _load_image_frames(images_dir: Path) -> list[tuple[str, bytes]]:
    exts = {".jpg", ".jpeg", ".png", ".bmp"}
    paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in exts)
    if not paths:
        raise SystemExit(f"No images found in {images_dir}")
    return [(p.name, p.read_bytes()) for p in paths]


def _load_labels(labels_path: Path) -> dict:
    """Simple ground-truth format this script understands:

        {
          "frame_001.jpg": {"person": 2, "product": 1},
          "frame_002.jpg": {"person": 1, "product": 0}
        }

    i.e. per-image expected counts by class (not full bounding boxes —
    box-level IoU matching would be a reasonable Sprint 2 follow-up once
    counts alone prove useful). Precision/recall/FP/FN below are computed
    at this per-image, per-class count level.
    """
    return json.loads(labels_path.read_text(encoding="utf-8"))


def _try_resource_proc():
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        proc.cpu_percent(interval=None)
        return proc
    except ImportError:
        return None


def run_one_config(
    label: str,
    env: dict[str, str],
    frames: list[tuple[str, bytes]],
    *,
    roi_yaml_path: str,
    with_yolo: bool,
    labels: dict | None,
    camera_key: str,
) -> dict:
    from app.vision.config import VisionConfig, reload_vision_config
    from app.vision.metrics.timers import MetricsRegistry
    from app.vision.pipeline import preprocess_for_detection

    known_flags = [k.upper() for k in vars(VisionConfig()).keys()]
    for k in list(os.environ.keys()):
        if k.startswith("ENABLE_") or k in known_flags:
            os.environ.pop(k, None)
    env = dict(env)
    if env.get("ENABLE_ROI") == "true" and "ROI_CONFIG_PATH" not in env:
        env["ROI_CONFIG_PATH"] = roi_yaml_path
    os.environ.update(env)
    cfg = reload_vision_config()
    MetricsRegistry.reset()

    yolo_model = None
    yolo_available = False
    if with_yolo:
        try:
            from ultralytics import YOLO

            yolo_model = YOLO(os.getenv("YOLO_MODEL", "yolov8n.pt"))
            yolo_available = True
        except Exception as exc:  # noqa: BLE001
            _log(f"  (--with-yolo requested but unavailable here: {exc})")

    proc = _try_resource_proc()

    opencv_ms, yolo_ms, total_ms = [], [], []
    low_quality = 0
    tp = fp = fn = 0
    person_counts, product_counts = [], []
    track_id_churn = []  # for a crude tracking-stability proxy, see report

    wall_start = time.perf_counter()
    prev_track_ids: set[int] | None = None
    for name, frame_bytes in frames:
        result = preprocess_for_detection(frame_bytes, camera_key, cfg)
        opencv_ms.append(result.opencv_ms)
        if result.quality is not None and result.quality.is_low_quality:
            low_quality += 1

        stage_yolo_ms = 0.0
        detected_counts: dict[str, int] = {}
        current_track_ids: set[int] = set()
        if yolo_model is not None:
            t0 = time.perf_counter()
            results = yolo_model.track(
                source=result.frame, persist=True, tracker="bytetrack.yaml", verbose=False
            )
            stage_yolo_ms = (time.perf_counter() - t0) * 1000.0
            yolo_ms.append(stage_yolo_ms)
            if results:
                r0 = results[0]
                names = r0.names or {}
                if r0.boxes is not None:
                    for box in r0.boxes:
                        cls_idx = int(box.cls[0]) if box.cls is not None else -1
                        cname = str(names.get(cls_idx, str(cls_idx)))
                        detected_counts[cname] = detected_counts.get(cname, 0) + 1
                        if box.id is not None:
                            current_track_ids.add(int(box.id[0]))
            person_counts.append(detected_counts.get("person", 0))
            product_counts.append(sum(v for k, v in detected_counts.items() if k != "person"))
            if prev_track_ids is not None:
                # crude churn proxy: ids that vanished + ids that appeared,
                # as a fraction of ids seen across the two frames. NOT a
                # substitute for MOTA/IDF1 — see report's caveats.
                union = prev_track_ids | current_track_ids
                if union:
                    churn = len(prev_track_ids ^ current_track_ids) / len(union)
                    track_id_churn.append(churn)
            prev_track_ids = current_track_ids

        total_ms.append(result.opencv_ms + stage_yolo_ms)

        if labels is not None and name in labels:
            expected = labels[name]
            for cls_name, exp_count in expected.items():
                got = detected_counts.get(cls_name, 0)
                tp += min(got, exp_count)
                fp += max(0, got - exp_count)
                fn += max(0, exp_count - got)

    wall_s = time.perf_counter() - wall_start
    cpu = proc.cpu_percent(interval=None) if proc else None
    rss = round(proc.memory_info().rss / (1024 * 1024), 1) if proc else None

    def _stats(vals):
        if not vals:
            return None
        s = sorted(vals)
        return {
            "mean": round(statistics.mean(vals), 3),
            "p95": round(s[int(len(s) * 0.95)], 3),
        }

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None

    return {
        "config": label,
        "env": env,
        "yolo_available": yolo_available,
        "frame_count": len(frames),
        "opencv_stage_ms": _stats(opencv_ms),
        "yolo_bytetrack_stage_ms": _stats(yolo_ms) if yolo_ms else None,
        "total_stage_ms": _stats(total_ms),
        "wall_fps": round(len(frames) / wall_s, 2) if wall_s > 0 else 0,
        "cpu_percent": cpu,
        "rss_mb": rss,
        "low_quality_flagged": low_quality,
        "avg_persons_per_frame": round(statistics.mean(person_counts), 2) if person_counts else None,
        "avg_products_per_frame": round(statistics.mean(product_counts), 2) if product_counts else None,
        "tracking_id_churn_proxy": round(statistics.mean(track_id_churn), 3) if track_id_churn else None,
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "false_positives": fp if labels is not None else None,
        "false_negatives": fn if labels is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=Path, default=None)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--iterations", type=int, default=150)
    parser.add_argument("--with-yolo", action="store_true")
    parser.add_argument("--labels", type=Path, default=None, help="Ground-truth JSON, see _load_labels docstring")
    parser.add_argument("--camera-key", default="eval-cam")
    args = parser.parse_args()

    if args.images:
        frames = _load_image_frames(args.images)
        source_desc = f"real images from {args.images}"
    else:
        raw = _make_synthetic_frames(args.iterations)
        frames = [(f"synthetic_{i:04d}.jpg", b) for i, b in enumerate(raw)]
        source_desc = "synthetic generated frames (NOT real camera footage)"

    labels = _load_labels(args.labels) if args.labels else None
    if args.labels and labels is None:
        _log("WARNING: --labels given but failed to load; precision/recall will be skipped")

    roi_yaml_path = "/tmp/sprint1_eval_roi.yaml"
    Path(roi_yaml_path).write_text(
        "cameras:\n"
        f"  {args.camera_key}:\n"
        "    zones:\n"
        "      - name: checkout\n"
        "        type: checkout\n"
        "        points: [[0.5,0.0],[1.0,0.0],[1.0,1.0],[0.5,1.0]]\n",
        encoding="utf-8",
    )

    _log(f"Sprint 1 evaluation — {len(frames)} frames ({source_desc})")
    _log(f"Python {platform.python_version()}  Platform {platform.platform()}")
    _log(f"--with-yolo: {args.with_yolo}   --labels: {args.labels}\n")

    all_results = []
    for label, env in CONFIGS:
        r = run_one_config(
            label, env, frames,
            roi_yaml_path=roi_yaml_path,
            with_yolo=args.with_yolo,
            labels=labels,
            camera_key=args.camera_key,
        )
        all_results.append(r)

    _log(f"{'config':<34}{'opencv_ms':<12}{'yolo_ms':<12}{'total_ms':<12}{'fps':<8}{'cpu%':<8}{'rss_mb':<9}{'persons':<9}{'products':<9}{'precision':<11}{'recall'}")
    _log("-" * 150)
    for r in all_results:
        ocv = r["opencv_stage_ms"]["mean"] if r["opencv_stage_ms"] else "-"
        yolo = r["yolo_bytetrack_stage_ms"]["mean"] if r["yolo_bytetrack_stage_ms"] else "n/a"
        tot = r["total_stage_ms"]["mean"] if r["total_stage_ms"] else "-"
        _log(
            f"{r['config']:<34}{ocv:<12}{yolo:<12}{tot:<12}{r['wall_fps']:<8}"
            f"{str(r['cpu_percent']):<8}{str(r['rss_mb']):<9}"
            f"{str(r['avg_persons_per_frame']):<9}{str(r['avg_products_per_frame']):<9}"
            f"{str(r['precision']):<11}{str(r['recall'])}"
        )

    if not args.with_yolo:
        _log(
            "\nNOTE: --with-yolo not set (or ultralytics/torch unavailable here) — "
            "yolo_ms/total_ms/persons/products/precision/recall above reflect the "
            "OpenCV preprocessing stage ONLY. See docs/OPENCV_SPRINT1_EVALUATION.md "
            "for what that does and doesn't tell you."
        )
    if labels is None:
        _log(
            "NOTE: --labels not given — precision/recall/false_positives/false_negatives "
            "are not computed (would need ground-truth counts per image)."
        )

    out_path = Path(__file__).resolve().parent / f"sprint1_eval_report_{int(time.time())}.json"
    out_path.write_text(
        json.dumps(
            {
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "with_yolo": args.with_yolo,
                    "source": source_desc,
                    "labels_used": str(args.labels) if args.labels else None,
                },
                "results": all_results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _log(f"\nFull JSON report: {out_path}")


if __name__ == "__main__":
    main()
