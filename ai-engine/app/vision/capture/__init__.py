"""Module 1 — OpenCV frame acquisition layer.

OpenCV was already doing frame capture in this project (see
`app/api/capture.py::_grab_frame`, `cv2.VideoCapture` + `cv2.imencode`) —
per the Sprint's own instruction ("If yes: do not replace it, improve it"),
this module wraps that existing function rather than replacing it, adding
timestamping, FPS measurement (per camera, based on inter-call cadence —
see `frame_source.py` docstring for why this measures *capture cadence*,
not true continuous-stream FPS), and dropped-frame counting.
"""

from __future__ import annotations

from app.vision.capture.frame_source import CaptureOutcome, instrumented_capture

__all__ = ["CaptureOutcome", "instrumented_capture"]
