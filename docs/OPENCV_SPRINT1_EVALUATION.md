# Sprint 1 Quantitative Evaluation (pre-Sprint 2 gate)

> **Status:** Partial — see §3 for exactly what could and could not be
> measured in this environment, and what's needed to finish it.
> **Script:** `ai-engine/scripts/sprint1_evaluation.py`
> **Date:** 2026-07-04

This document evaluates the 7 requested configurations before any Sprint 2
work begins, per instruction. It does not recommend or implement anything
from Sprint 2.

## 1. Configurations Tested

| # | Configuration | Flags |
| - | -------------- | ----- |
| 1 | Baseline (no preprocessing) | none |
| 2 | Brightness/Contrast only | `ENABLE_BRIGHTNESS_ADJUST`, `ENABLE_CONTRAST_ADJUST` |
| 3 | CLAHE only | `ENABLE_CLAHE` |
| 4 | Histogram Equalization only | `ENABLE_HIST_EQ` |
| 5 | Gamma Correction only | `ENABLE_GAMMA` |
| 6 | CLAHE + Gamma | `ENABLE_CLAHE` + `ENABLE_GAMMA` |
| 7 | Full preprocessing pipeline | ROI + every Module 3 enhancement + quality/blur analysis |

## 2. Environment This Evaluation Ran In (read this before the numbers)

This was run in a **CPU-only development sandbox**, not the production
VPS, and **without `ultralytics`/`torch` installed** — the CPU-only torch
wheel alone is ~530MB, and this sandbox's network path to both
`download.pytorch.org` (proxy returns 403) and PyPI (times out on a
532MB transfer) could not complete it within this session. There is also
**no labeled dataset or real camera footage** available anywhere in this
repository or upload area (checked: `models/`, `ai-engine/training/datasets/`
are empty placeholders; no images/video files exist in the repo; nothing
was uploaded this session).

Consequently, this evaluation honestly splits into two parts:

- **§3 — Measured for real, right now:** OpenCV preprocessing-stage cost
  (time, FPS, CPU, memory) across all 7 configurations, on synthetic
  frames, in this sandbox.
- **§4 — Not measured, and why:** YOLO inference time, total pipeline
  latency, precision/recall/FP/FN, tracking stability, and customer/product
  counts. None of these are guessed or estimated below — they're marked
  as open, with exactly what's needed to close them.

## 3. Measured: OpenCV Preprocessing Stage Cost

150 synthetic 1280x720 frames, each config run in isolation (fresh
`VisionConfig` reload between configs, `MetricsRegistry` reset). Reproduced
three times; numbers below are stable to within ~5%.

| Config | OpenCV stage mean | OpenCV stage p95 | Stage-only FPS | CPU % | RSS MB |
| ------ | -----------------: | -----------------: | --------------: | -----: | ------: |
| 1. Baseline | 4.7 ms | 5.6 ms | ~209 | 100% | 91 |
| 2. Brightness/Contrast | 6.6 ms | 7.5 ms | ~151 | 100% | 97 |
| 3. CLAHE only | 20.2 ms | 22.9 ms | ~50 | 172% | 109 |
| 4. Histogram Equalization | 17.0 ms | 21.4 ms | ~59 | 172% | 109 |
| 5. Gamma Correction | 5.9 ms | 6.7 ms | ~170 | 128% | 109 |
| 6. CLAHE + Gamma | 20.2 ms | 24.0 ms | ~49 | 176% | 112 |
| 7. Full pipeline | 60.3 ms | 66.1 ms | ~16.5 | 152% | 122 |

**What this tells you, precisely:** relative cost ordering between the
configurations, on this hardware, for the OpenCV stage alone. Options 3, 4,
6, and 7 add meaningful latency (12-56ms/frame); options 2 and 5 are
nearly free (+1-2ms/frame).

**What this does NOT tell you:** how any of this compares once real YOLO
inference (typically 80-150ms/frame for yolov8n on CPU, per public
benchmarks — not verified against this project's own weights/hardware) is
added on top, or whether any configuration changes detection outcomes at
all. See §4.

## 4. Not Measured (and what's needed to close each gap)

| Metric | Status | What's needed |
| ------ | ------ | -------------- |
| YOLO inference time | Not measured | `ultralytics` + `torch` importable in the run environment. Already true on the deployed ai-engine container (see its `Dockerfile`) — run `scripts/sprint1_evaluation.py --with-yolo` there. |
| Total pipeline latency | Not measured | Same as above (it's OpenCV + YOLO time combined). |
| Detection precision / recall | Not measured | Ground-truth labels for a real sample (see `--labels` format in the script's docstring — simple per-image, per-class expected counts). No labeled data exists in this repo currently. |
| False positives / false negatives | Not measured | Same as precision/recall. |
| Tracking stability (ByteTrack) | Not measured | Real sequential footage where track continuity has a knowable right answer (a person shouldn't gain/lose their track id while still in frame). The script includes a *crude* proxy (`tracking_id_churn_proxy` — fraction of track ids that appear/disappear frame-to-frame) that only becomes meaningful on a real video sequence, not independent synthetic frames. |
| Number of detected customers | Not measured | Real YOLO + real footage with actual people in frame (synthetic shapes are not recognizable as the `person` class). |
| Number of detected products | Not measured | Real YOLO + either this store's actual product classes/trained weights, or COCO classes as a rough stand-in — either way, real footage. |

**None of these six were estimated, simulated, or backfilled with
plausible-looking numbers.** Doing so would fail the review standard this
project has held to since the pre-production audit — reporting a fabricated
precision/recall number would be actively worse than reporting "not
measured," because it would look authoritative while being invented.

## 5. What Can Be Concluded Now

- Options **2 (Brightness/Contrast)** and **5 (Gamma)** are cheap (≤2ms
  overhead) regardless of what the accuracy numbers eventually show —
  low risk to enable if a future accuracy check finds them useful.
- Options **3 (CLAHE)**, **4 (Histogram Equalization)**, and **7 (Full
  pipeline)** are the expensive ones (12-56ms overhead) and currently have
  **zero measured evidence of accuracy benefit** to justify that cost —
  consistent with the Sprint 1 report's existing recommendation to leave
  them off by default.
- **6 (CLAHE + Gamma)** costs almost exactly the same as CLAHE alone
  (20.2ms vs 20.4ms) — Gamma's own cost is negligible next to CLAHE's, so
  if CLAHE is ever justified by real accuracy data, adding Gamma on top is
  nearly free.

## 6. Recommended Default Production Configuration (provisional)

**Recommendation: keep every `vision/` feature at its current default —
all off (Configuration 1, Baseline) — until §4's accuracy metrics exist.**

This is a provisional recommendation based on cost data only. It is the
correct call under the evidence available right now: none of the 6
enhancement/ROI/quality features has demonstrated an accuracy benefit, two
of them cost meaningfully more CPU per frame on the current VPS-class
hardware, and the project's own stated policy (Sprint 1 brief) is to
disable anything that costs without proven benefit.

If/when real accuracy data becomes available (§4), the recommendation
should be revisited using this decision rule: enable a feature only if its
measured precision/recall/FP/FN improvement is large enough to justify its
measured ms/frame cost from §3 — not before.

## 7. How to Finish This Evaluation

To close the gaps in §4, either:

**Option A — run it on the VPS** (has `torch`/`ultralytics` already
installed):

```bash
# copy a handful of real frames (or a short clip split into frames) from
# an actual store camera onto the VPS, then:
python scripts/sprint1_evaluation.py --images /path/to/real_frames --with-yolo
```

This alone gets YOLO inference time, total latency, and real person/product
counts — still without precision/recall (needs labels).

**Option B — provide a small labeled sample.** A dozen or two representative
frames with a simple JSON of expected counts per class
(`{"frame_001.jpg": {"person": 2, "product": 1}, ...}`) is enough to get
precision/recall/FP/FN via `--labels`. Doesn't need to be exhaustive —
enough frames to see a trend per configuration.

Either result (or both) can be pasted/attached back and this document will
be updated with the real numbers before any Sprint 2 recommendation is
finalized.

---

_No Sprint 2 code was written. This document only evaluates Sprint 1._
