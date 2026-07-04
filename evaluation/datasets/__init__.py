"""Dataset loaders: image folders, video files, RTSP/camera recordings, and
optional ground-truth annotations.

All loaders produce the same `Frame` interface so every downstream metric
module (pipeline, detection, tracking, camera quality) works identically
regardless of input type — this is what "Support evaluation from: Image
folders / Video files / RTSP recordings / Camera recordings" means in
practice: RTSP/camera recordings are video files once captured, so
`VideoFileDataset` covers all three; `RtspRecordingDataset` and
`CameraRecordingDataset` are documented aliases for clarity in CLI help
text and reports.
"""

from __future__ import annotations

from evaluation.datasets.loaders import (
    CameraRecordingDataset,
    Frame,
    ImageFolderDataset,
    RtspRecordingDataset,
    VideoFileDataset,
    load_dataset,
)
from evaluation.datasets.annotations import GroundTruthBox, load_annotations

__all__ = [
    "Frame",
    "ImageFolderDataset",
    "VideoFileDataset",
    "RtspRecordingDataset",
    "CameraRecordingDataset",
    "load_dataset",
    "GroundTruthBox",
    "load_annotations",
]
