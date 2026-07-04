"""OpenCV Computer Vision layer — sits between raw camera/RTSP frame bytes
and YOLO/ByteTrack.

Boundaries (see module docstrings for detail):
  capture/      OpenCV frame acquisition (RTSP/video grab, FPS, dropped frames)
  roi/          Optional Region-Of-Interest masking, loaded from config
  enhancement/  Optional classical preprocessing (CLAHE, gamma, blur, ...)
  quality/      Frame quality analysis (blur/brightness/contrast), never drops frames
  metrics/      Per-stage timing + per-camera FPS bookkeeping
  overlay/      Optional debug visualization (off by default)

Everything here is additive and individually toggleable via environment
variables (see `config.py`). With every ``ENABLE_*`` flag left at its
default (off), `pipeline.preprocess_for_detection()` decodes the frame and
returns it unchanged — byte-for-byte equivalent to how `person_tracker.py`
used to decode via PIL before this module existed. YOLO, ByteTrack, and
everything in the backend (cart/checkout/event bus/API contract) are
untouched by this package.
"""

from __future__ import annotations
