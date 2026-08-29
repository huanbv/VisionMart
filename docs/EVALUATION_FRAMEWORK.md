# VisionMart Experimental Evaluation Framework

> **Package:** `evaluation/` (top-level, standalone from `backend/` and `ai-engine/`)
> **Status:** Complete and verified in this sandbox with synthetic frames and OpenCV-stage-only metrics (no `ultralytics`/`torch`, no real footage — see §7). Designed and written to work correctly end-to-end with real YOLO/ByteTrack and real footage on the ai-engine container/VPS.
> **Date:** 2026-07-04

## 1. Purpose and Scope

This framework produces the quantitative evidence needed for the graduation
thesis defense: a reproducible comparison of 7 OpenCV preprocessing
configurations, publication-quality charts, and CSV/XLSX/JSON/Markdown
reports — **without touching production code, schema, APIs, or data.**

Hard constraints this framework respects (see module docstrings for where
each is enforced in code):

- Does not modify the checkout pipeline, database schema, APIs, Shopping
  Cart logic, or Event Bus. It only *imports* `ai-engine/app/vision/*` for
  measurement fidelity (same preprocessing code path production uses) and
  *reads* (never writes) the backend's Postgres database for cart/order/
  camera metrics.
- `evaluation/cart/cart_metrics.py` opens its own read-only DB session,
  issues `SET TRANSACTION READ ONLY` when the backend supports it (Postgres
  does), and only ever executes `select()` statements — never
  `session.add`/`session.commit`/`checkout_service.*`/`cart_service.*`.
- Every metric that cannot be measured (missing labels, no YOLO installed,
  data not persisted anywhere in the schema) is reported as `null`/`None`
  with an explicit reason string — never estimated or guessed.

## 2. Package Layout

```
evaluation/
  config.py                       7 PreprocessingConfig + 9 OpenCvModule definitions (single source of truth)
  cli.py                          CLI entrypoint (evaluate / cart-metrics / thesis-report)
  datasets/
    loaders.py                    ImageFolderDataset, VideoFileDataset (+ Rtsp/Camera aliases), load_dataset()
    annotations.py                Ground-truth loading (box-level + count-level formats)
  metrics/
    pipeline_metrics.py           Timing, FPS, CPU/RAM/GPU, dropped frames, derived ByteTrack timing
    camera_quality_metrics.py     Brightness, contrast, blur, noise, motion %, frozen-frame detection
    detection_metrics.py          Precision/recall/F1/confusion matrix (IoU or count-level)
    tracking_metrics.py           Track lifetime, fragmentation, continuity, ID-churn proxy, ID switches
    opencv_module_eval.py         Per-module isolated cost/benefit + ON/OFF recommendation
  cart/
    cart_metrics.py                Read-only Shopping Cart / Order / Camera DB metrics
  reporting/
    types.py                       RunResult / ConfigRunResult containers
    exporters.py                   CSV / XLSX / JSON export
    charts.py                      matplotlib comparison charts
    markdown_report.py             Per-run Markdown summary
    thesis_report.py               Full thesis-style Markdown (Setup/Methodology/Results/.../Conclusions)
```

## 3. Why `evaluate` and `cart-metrics` Are Separate Processes

`evaluate` imports ai-engine's `app.vision.*` package. `cart-metrics`
imports backend's `app.modules.*` package. **Both services define their
own, unrelated top-level `app` package** — importing both into one Python
interpreter is unsafe (whichever is imported first wins the `app` name in
`sys.modules`, and the other import silently returns the wrong code).
`evaluation/cli.py` therefore never imports both in the same process:
run `cart-metrics` separately, save its JSON, and pass it to `evaluate`
(or `thesis-report`) via `--cart-metrics-json`.

## 4. Preparing a Dataset

| Input type | How to prepare | CLI flag |
| --- | --- | --- |
| Image folder | A directory of `.jpg`/`.jpeg`/`.png`/`.bmp` files | `--input-kind images --input <dir>` |
| Video file | Any file OpenCV can open (`.mp4`, `.avi`, `.mov`, `.mkv`, `.ts`) | `--input-kind video --input <file>` |
| RTSP recording | A video file saved from an RTSP stream — same as "Video file" | `--input-kind rtsp --input <file>` |
| Live RTSP stream | Pass the `rtsp://...` URL directly — OpenCV opens it transparently; frame count is unknown ahead of time, so use `--max-frames` | `--input-kind rtsp --input rtsp://...` |
| Camera recording | A video file saved from a store camera — same as "Video file" | `--input-kind camera --input <file>` |

**Ground truth (optional, for detection metrics):** a JSON file, one of two formats — see `evaluation/datasets/annotations.py` for the full spec:

```json
// Box-level (enables IoU matching, per-class metrics, confusion matrix)
{ "frame_0001.jpg": [ {"class": "person", "bbox": [120, 80, 340, 500]} ] }

// Count-level (coarser fallback)
{ "frame_0001.jpg": {"person": 2, "product": 1} }
```

Frames present in the dataset but absent from the annotation file are
excluded from detection metrics (not counted as zero objects), so a
partially labeled dataset doesn't deflate recall.

## 5. Running an Evaluation

```bash
# Cost-only comparison, no YOLO/labels needed, works anywhere:
python -m evaluation.cli evaluate --input-kind images --input /data/frames

# Full comparison with real YOLO + labels + per-module evaluation
# (run where ultralytics/torch are installed — the ai-engine container/VPS):
python -m evaluation.cli evaluate \
    --input-kind images --input /data/frames \
    --with-yolo --labels /data/labels.json --run-opencv-modules

# Video file (also correct for a saved RTSP or camera recording):
python -m evaluation.cli evaluate \
    --input-kind video --input /data/store_cam1.mp4 \
    --with-yolo --sample-every-n-frames 3

# Live RTSP stream, capped at 600 sampled frames:
python -m evaluation.cli evaluate \
    --input-kind rtsp --input rtsp://192.168.1.50/stream1 \
    --with-yolo --max-frames 600

# Cart/order/camera metrics — run on the VPS where DATABASE_URL is reachable:
python -m evaluation.cli cart-metrics \
    --database-url postgresql+asyncpg://user:pass@host/db \
    --window-start 2026-07-01T00:00:00 --window-end 2026-07-04T00:00:00

# Fold the cart metrics into a report generated earlier:
python -m evaluation.cli thesis-report \
    --run-json ./evaluation_results/evaluation_20260704_120000.json \
    --cart-metrics-json ./evaluation_results/cart_metrics_20260704_120500.json
```

Every run produces, in `--output-dir` (default `./evaluation_results`):

- `evaluation_<run_id>.json` — full raw results
- `pipeline_metrics_<run_id>.csv`, `camera_quality_metrics_<run_id>.csv`, `detection_metrics_<run_id>.csv`, `tracking_metrics_<run_id>.csv`, `opencv_module_evaluation_<run_id>.csv`, `cart_metrics_<run_id>.csv` (only the tables that had data)
- `evaluation_<run_id>.xlsx` — same tables as workbook sheets
- `*_<run_id>.png` — one chart per measured metric (FPS, CPU, Memory, Latency, Detection Count, Tracking Count, Blur Score, Brightness, Quality Score, Pipeline Time, Frame Time)
- `evaluation_report_<run_id>.md` — per-run Markdown summary
- `thesis_report_<run_id>.md` — full thesis-style report (Setup, Hardware, Software, Dataset, Methodology, Results, Comparison, Discussion, Limitations, Future Work, Conclusions)

## 6. Interpreting the Metrics

- **Pipeline metrics** (`avg_fps`, `opencv_stage`/`yolo_stage`/`bytetrack_stage`/`total_stage` mean/p50/p95, `cpu_percent_avg`, `rss_mb_avg`, `dropped_frames`): `bytetrack_stage` is a *derived* estimate (`track() - predict()` wall time on the same frame, clamped ≥ 0) because ultralytics doesn't expose ByteTrack timing separately — always labeled as such, never presented as a hardware trace.
- **Camera quality** (`brightness_avg`, `blur_score_avg`, `quality_score_avg`, `motion_percent_avg`, `frozen_frame_pct`): computed with the same formulas as `ai-engine/app/vision/quality/analyzer.py`, so these numbers are directly comparable to what production would report for the same frame.
- **Detection metrics**: `measurable=False` with a `reason` field when no ground truth was supplied — never a fabricated precision/recall.
- **Tracking metrics**: `id_switch_count` is `None` unless you supply `gt_identity_map` (MOT-style cross-frame identity ground truth); the `id_churn_proxy` field is a rough continuity signal only, explicitly not a substitute.
- **OpenCV module evaluation**: a module is only recommended `ON` when a real, measured detection improvement (via `--with-yolo`) offsets its measured cost. Without `--with-yolo`, every module is recommended `OFF` with the reason "benefit not measured" — never "assumed ineffective."
- **Cart metrics**: `checkout_cancelled_count`, `qr_confirmation_count`, and per-camera `camera_uptime_percent` are `None` by design — the underlying data isn't persisted anywhere in the current schema (see `cart_metrics.py`'s docstring for the exact code paths checked). `camera_online_now_count`/`camera_total_count` (an instantaneous snapshot) is reported instead.

## 7. Reproducing Experiments / What Ran in This Sandbox

This development sandbox has **no `ultralytics`/`torch`** (the ~530MB CPU
torch wheel could not be downloaded here — see `docs/OPENCV_SPRINT1_EVALUATION.md` §2 for the exact failure) and **no real labeled data or camera
footage** anywhere in the repository. Every metric in this framework was
therefore verified in this sandbox using:

1. Unit-level tests of each collector/aggregator against hand-built inputs
   with known expected outputs (IoU matching, ID-switch detection, cart
   aggregation against the real `CartStatus`/`OrderStatus` enums).
2. A full `python -m evaluation.cli evaluate --synthetic-frames N --run-opencv-modules` smoke run, proving every stage of the pipeline — collectors → `RunResult` → JSON/CSV/XLSX export → chart generation → Markdown/thesis report — works end to end and produces internally consistent, real (not fabricated) measured numbers for the OpenCV preprocessing stage.

**Synthetic-frame numbers are for CI/wiring verification only** and are
explicitly labeled as such in every generated report (`dataset.kind ==
"synthetic"` triggers a Limitations note). They must not be cited as real
detection accuracy or real-world camera quality results in the thesis.

### VPS Instructions for Real Supermarket Footage

1. On the VPS/ai-engine container (where `ultralytics`/`torch` are already
   installed per its Dockerfile), copy or mount `evaluation/` alongside
   `ai-engine/`.
2. Collect frames: either point `--input-kind images` at a folder of
   exported frames, `--input-kind video`/`camera` at a saved recording, or
   `--input-kind rtsp` directly at a camera's RTSP URL with `--max-frames`
   set.
3. If you have or can produce ground truth (even a partial, count-level
   set is useful), pass `--labels`.
4. Run: `python -m evaluation.cli evaluate --input-kind video --input /data/real_footage.mp4 --with-yolo --labels /data/labels.json --run-opencv-modules --output-dir /data/eval_results`
5. Separately, run `cart-metrics` against the VPS's `DATABASE_URL` for the
   same time window and merge it in with `--cart-metrics-json`.
6. Re-run `thesis-report` (or just re-run `evaluate`) to get the final
   thesis-ready Markdown with real numbers throughout.

## 8. Recommendation for Production Configuration

Based on every measurement actually collected in this sandbox (OpenCV-stage
cost only — see §7): **CLAHE and Histogram Equalization are consistently
the most expensive single operations** (confirmed independently in both
this framework and the earlier Sprint 1 evaluation, `docs/OPENCV_SPRINT1_EVALUATION.md`), while Brightness/Contrast and Gamma Correction are
cheap. No module has a *measured* detection or tracking benefit yet — that
requires a `--with-yolo` run on real, ideally labeled, footage. Until that
run happens, this framework's own per-module evaluation logic recommends
every module `OFF` (matching the Sprint 1 evaluation's provisional
recommendation to keep all Sprint 1 features off by default). This is not
a claim that the modules don't help — only that their benefit hasn't been
measured yet, and this framework refuses to recommend enabling anything
without measured benefit, per its explicit design constraint.
