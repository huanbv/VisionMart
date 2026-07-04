"""Concrete dataset loaders.

Every loader yields `Frame` objects with the same shape, so
`evaluation/runner.py` never needs to know whether the input was a folder
of JPEGs or a decoded video.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("evaluation.datasets")

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".ts"}


@dataclass(frozen=True)
class Frame:
    name: str                  # stable id, used to match ground-truth annotations
    image_bytes: bytes         # JPEG-encoded bytes (consistent with the production pipeline's input)
    frame_index: int
    timestamp_s: float | None  # video position, None for standalone images


class ImageFolderDataset:
    """A directory of still images — one "frame" per file, sorted by name
    for reproducible ordering across runs."""

    def __init__(self, path: str | Path, limit: int | None = None) -> None:
        self.path = Path(path)
        if not self.path.is_dir():
            raise NotADirectoryError(f"{self.path} is not a directory")
        self._paths = sorted(p for p in self.path.iterdir() if p.suffix.lower() in _IMAGE_EXTS)
        if not self._paths:
            raise SystemExit(f"No images (jpg/jpeg/png/bmp) found in {self.path}")
        if limit is not None:
            self._paths = self._paths[:limit]
        self.dropped_frames = 0  # images never "drop" — kept for interface symmetry

    def __len__(self) -> int:
        return len(self._paths)

    def __iter__(self) -> Iterator[Frame]:
        for i, p in enumerate(self._paths):
            yield Frame(name=p.name, image_bytes=p.read_bytes(), frame_index=i, timestamp_s=None)


class VideoFileDataset:
    """A video file (mp4/avi/mov/...) — also the right loader for a saved
    RTSP recording or a saved camera recording, since both are ordinary
    video files once captured to disk. For a *live* RTSP stream (no prior
    recording), pass the `rtsp://...` URL as `path` directly; OpenCV's
    `cv2.VideoCapture` accepts both transparently. Live streams have an
    unknown frame count (`len()` returns -1) and "dropped frames" means
    "read() failed mid-stream" rather than "frame missing from a file with
    a known total", which is called out explicitly in reports generated
    from a live-stream run.
    """

    def __init__(
        self,
        path: str,
        sample_every_n_frames: int = 1,
        max_frames: int | None = None,
        jpeg_quality: int = 90,
    ) -> None:
        self.path = str(path)
        self.sample_every_n_frames = max(1, sample_every_n_frames)
        self.max_frames = max_frames
        self.jpeg_quality = jpeg_quality
        self.dropped_frames = 0
        self._is_file = Path(self.path).is_file() if not self.path.startswith(("rtsp://", "http://", "https://")) else False
        if self._is_file and not Path(self.path).exists():
            raise FileNotFoundError(self.path)

    def __len__(self) -> int:
        import cv2

        if not self._is_file:
            return -1  # unknown for live streams
        cap = cv2.VideoCapture(self.path)
        try:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()
        return max(0, (total + self.sample_every_n_frames - 1) // self.sample_every_n_frames)

    def __iter__(self) -> Iterator[Frame]:
        import cv2

        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video source: {self.path}")
        self.dropped_frames = 0
        raw_index = 0
        kept_index = 0
        try:
            while True:
                if self.max_frames is not None and kept_index >= self.max_frames:
                    break
                ok, frame = cap.read()
                if not ok or frame is None:
                    # End of file is a normal `ok=False` too — we can't tell
                    # "stream ended" from "one bad read" with OpenCV's API
                    # alone. For a file with a known frame count, the
                    # caller can compare `kept_index` against `len(self)`
                    # afterwards to see if frames were actually dropped;
                    # for a live stream this counter is the only signal.
                    if self._is_file:
                        break
                    self.dropped_frames += 1
                    raw_index += 1
                    continue
                if raw_index % self.sample_every_n_frames == 0:
                    ok_enc, buf = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
                    )
                    if not ok_enc:
                        self.dropped_frames += 1
                        raw_index += 1
                        continue
                    ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                    yield Frame(
                        name=f"frame_{kept_index:06d}.jpg",
                        image_bytes=buf.tobytes(),
                        frame_index=kept_index,
                        timestamp_s=(ts_ms / 1000.0) if ts_ms and ts_ms > 0 else None,
                    )
                    kept_index += 1
                raw_index += 1
        finally:
            cap.release()


# Documented aliases — same implementation, different name so CLI help
# text and generated reports say what the input actually was.
RtspRecordingDataset = VideoFileDataset
CameraRecordingDataset = VideoFileDataset


def load_dataset(kind: str, path: str, **kwargs):
    """CLI convenience dispatcher. `kind` in {"images", "video", "rtsp", "camera"}."""
    kind = kind.lower()
    if kind == "images":
        return ImageFolderDataset(path, limit=kwargs.get("limit"))
    if kind == "video":
        return VideoFileDataset(
            path,
            sample_every_n_frames=kwargs.get("sample_every_n_frames", 1),
            max_frames=kwargs.get("max_frames"),
        )
    if kind in ("rtsp", "camera"):
        return RtspRecordingDataset(
            path,
            sample_every_n_frames=kwargs.get("sample_every_n_frames", 1),
            max_frames=kwargs.get("max_frames"),
        )
    raise ValueError(f"Unknown dataset kind: {kind!r} (expected images|video|rtsp|camera)")
