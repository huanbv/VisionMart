"""Optional ground-truth annotation loading.

Two supported JSON formats, auto-detected per frame entry:

Box-level (preferred — enables IoU-based matching, per-class metrics, and
a real confusion matrix)::

    {
      "frame_0001.jpg": [
        {"class": "person", "bbox": [120, 80, 340, 500]},
        {"class": "product", "bbox": [400, 200, 460, 280]}
      ],
      "frame_0002.jpg": []
    }

Count-only (coarser — only enables per-class TP/FP/FN at the *count*
level, no IoU, no confusion matrix; kept for compatibility with the
Sprint 1 evaluation's simpler format and for datasets where only "how many
of each class" was labeled, not exact boxes)::

    {
      "frame_0001.jpg": {"person": 2, "product": 1}
    }

Frames present in the dataset but absent from the annotation file are
treated as "no ground truth for this frame" and excluded from detection
metrics (not counted as zero objects) — this matters because a partially
labeled dataset must not silently deflate recall.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GroundTruthBox:
    class_name: str
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2


@dataclass(frozen=True)
class GroundTruth:
    """Normalized annotations for one dataset."""

    by_frame_boxes: dict[str, list[GroundTruthBox]]   # only frames with box-level labels
    by_frame_counts: dict[str, dict[str, int]]          # only frames with count-only labels
    has_boxes: bool                                      # True if ANY frame has box-level labels

    def labeled_frame_names(self) -> set[str]:
        return set(self.by_frame_boxes) | set(self.by_frame_counts)


def load_annotations(path: str | Path) -> GroundTruth:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    by_boxes: dict[str, list[GroundTruthBox]] = {}
    by_counts: dict[str, dict[str, int]] = {}
    has_boxes = False

    for frame_name, entry in raw.items():
        if isinstance(entry, list):
            boxes = []
            for item in entry:
                bbox = item["bbox"]
                boxes.append(
                    GroundTruthBox(
                        class_name=str(item["class"]),
                        bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    )
                )
            by_boxes[frame_name] = boxes
            has_boxes = True
        elif isinstance(entry, dict):
            by_counts[frame_name] = {str(k): int(v) for k, v in entry.items()}
        else:
            raise ValueError(
                f"Annotation for {frame_name!r} must be a list (box format) "
                f"or an object (count format), got {type(entry).__name__}"
            )

    return GroundTruth(by_frame_boxes=by_boxes, by_frame_counts=by_counts, has_boxes=has_boxes)
