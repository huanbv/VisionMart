"""VisionMart Experimental Evaluation Framework.

Standalone, read-only, offline analysis of the existing Computer Vision +
cart pipeline for thesis-quality quantitative evidence. This package is
deliberately separate from `ai-engine/` and `backend/`:

  - It imports the existing `ai-engine/app/vision` preprocessing pipeline
    and `ai-engine` YOLO/ByteTrack code to *reuse* them for benchmarking,
    but never modifies them.
  - It reads (never writes) the backend's database for cart/checkout
    statistics — see `evaluation/cart/cart_metrics.py`'s module docstring
    for the exact read-only guarantee.
  - It does not start, depend on, or talk to any running production
    service over the network. Everything here operates on files (images,
    videos, an optional exported DB dump / read-only DB connection) you
    give it.

Nothing in this package is imported by `ai-engine` or `backend` — the
dependency direction is one-way (evaluation -> production code), so
running an evaluation can never affect production behaviour.

See docs/EVALUATION_FRAMEWORK.md for how to run this.
"""

from __future__ import annotations
