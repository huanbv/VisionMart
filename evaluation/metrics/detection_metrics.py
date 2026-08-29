"""Detection accuracy metrics: precision / recall / F1 / confusion matrix.

Only produces numbers when ground truth is available (`GroundTruth` from
`evaluation/datasets/annotations.py`, either box-level or count-level, see
that module's docstring). When no ground truth was supplied, every
function here returns a result object with `measurable=False` and a
`reason` string — callers (reporting/*, thesis report generator) must
surface that reason verbatim rather than omitting the metric silently or
substituting a placeholder value.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from evaluation.datasets.annotations import GroundTruth, GroundTruthBox


@dataclass(frozen=True)
class Detection:
    class_name: str
    bbox: tuple[float, float, float, float] | None  # None if only count-level detections are available
    confidence: float | None = None


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@dataclass
class DetectionMetricsResult:
    measurable: bool
    reason: str
    method: str | None = None  # "box_iou" or "count_only"
    frames_evaluated: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    avg_confidence: float | None = None
    detection_count: int = 0
    missed_detection_count: int = 0
    per_class: dict = field(default_factory=dict)
    confusion_matrix: dict | None = None  # only populated for method == "box_iou"


class DetectionMetricsCollector:
    """Feed one frame at a time via `add_frame`, call `summary()` at the
    end. If `ground_truth` has no labeled frames at all, every `add_frame`
    call is a no-op and `summary()` reports `measurable=False`.
    """

    def __init__(self, ground_truth: GroundTruth | None, iou_threshold: float = 0.5) -> None:
        self.ground_truth = ground_truth
        self.iou_threshold = iou_threshold
        self.method: str | None = None
        if ground_truth is not None and ground_truth.labeled_frame_names():
            self.method = "box_iou" if ground_truth.has_boxes else "count_only"
        self._frames_evaluated = 0
        self._tp = 0
        self._fp = 0
        self._fn = 0
        self._confidences: list[float] = []
        self._per_class: dict[str, dict[str, int]] = {}
        self._confusion: dict[str, dict[str, int]] = {}
        self._detection_count = 0

    @property
    def measurable(self) -> bool:
        return self.method is not None

    def _bump_class(self, cls: str, key: str, n: int = 1) -> None:
        self._per_class.setdefault(cls, {"tp": 0, "fp": 0, "fn": 0})
        self._per_class[cls][key] += n

    def add_frame(self, frame_name: str, detections: list[Detection]) -> None:
        if not self.measurable or self.ground_truth is None:
            return
        self._detection_count += len(detections)
        for d in detections:
            if d.confidence is not None:
                self._confidences.append(d.confidence)

        if self.method == "box_iou":
            gt_boxes = self.ground_truth.by_frame_boxes.get(frame_name)
            if gt_boxes is None:
                return  # unlabeled frame — excluded, not counted as zero GT
            self._frames_evaluated += 1
            matched_gt = [False] * len(gt_boxes)
            # Greedy match: highest-confidence detections first.
            dets_sorted = sorted(
                [d for d in detections if d.bbox is not None],
                key=lambda d: d.confidence if d.confidence is not None else 0.0,
                reverse=True,
            )
            for d in dets_sorted:
                best_iou, best_idx = 0.0, -1
                for i, gt in enumerate(gt_boxes):
                    if matched_gt[i]:
                        continue
                    iou = _iou(d.bbox, gt.bbox)
                    if iou > best_iou:
                        best_iou, best_idx = iou, i
                if best_idx >= 0 and best_iou >= self.iou_threshold:
                    matched_gt[best_idx] = True
                    gt_cls = gt_boxes[best_idx].class_name
                    self._confusion.setdefault(gt_cls, {}).setdefault(d.class_name, 0)
                    self._confusion[gt_cls][d.class_name] += 1
                    if d.class_name == gt_cls:
                        self._tp += 1
                        self._bump_class(gt_cls, "tp")
                    else:
                        # Localized correctly, wrong class: FP for predicted
                        # class, FN for the true class.
                        self._fp += 1
                        self._fn += 1
                        self._bump_class(d.class_name, "fp")
                        self._bump_class(gt_cls, "fn")
                else:
                    self._fp += 1
                    self._bump_class(d.class_name, "fp")
            for i, gt in enumerate(gt_boxes):
                if not matched_gt[i]:
                    self._fn += 1
                    self._bump_class(gt.class_name, "fn")
                    self._confusion.setdefault(gt.class_name, {}).setdefault("__missed__", 0)
                    self._confusion[gt.class_name]["__missed__"] += 1

        else:  # count_only
            gt_counts = self.ground_truth.by_frame_counts.get(frame_name)
            if gt_counts is None:
                return
            self._frames_evaluated += 1
            det_counts: dict[str, int] = {}
            for d in detections:
                det_counts[d.class_name] = det_counts.get(d.class_name, 0) + 1
            classes = set(gt_counts) | set(det_counts)
            for cls in classes:
                exp = gt_counts.get(cls, 0)
                got = det_counts.get(cls, 0)
                tp = min(got, exp)
                fp = max(0, got - exp)
                fn = max(0, exp - got)
                self._tp += tp
                self._fp += fp
                self._fn += fn
                self._bump_class(cls, "tp", tp)
                self._bump_class(cls, "fp", fp)
                self._bump_class(cls, "fn", fn)

    def summary(self) -> DetectionMetricsResult:
        if not self.measurable:
            return DetectionMetricsResult(
                measurable=False,
                reason=(
                    "No ground-truth annotations were provided for this dataset "
                    "(pass --labels). Precision/recall/F1/confusion-matrix cannot "
                    "be calculated and are not estimated."
                ),
            )
        if self._frames_evaluated == 0:
            return DetectionMetricsResult(
                measurable=False,
                reason=(
                    "Ground truth was provided but none of its labeled frame names "
                    "matched any frame produced by this dataset run — check that "
                    "annotation keys match the frame names used by the loader."
                ),
            )

        precision = self._tp / (self._tp + self._fp) if (self._tp + self._fp) > 0 else None
        recall = self._tp / (self._tp + self._fn) if (self._tp + self._fn) > 0 else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and (precision + recall) > 0
            else None
        )

        per_class_out = {}
        for cls, c in self._per_class.items():
            p = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) > 0 else None
            r = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) > 0 else None
            per_class_out[cls] = {
                "tp": c["tp"], "fp": c["fp"], "fn": c["fn"],
                "precision": round(p, 3) if p is not None else None,
                "recall": round(r, 3) if r is not None else None,
            }

        return DetectionMetricsResult(
            measurable=True,
            reason="Measured from provided ground-truth annotations.",
            method=self.method,
            frames_evaluated=self._frames_evaluated,
            tp=self._tp, fp=self._fp, fn=self._fn,
            precision=round(precision, 3) if precision is not None else None,
            recall=round(recall, 3) if recall is not None else None,
            f1=round(f1, 3) if f1 is not None else None,
            avg_confidence=round(statistics.mean(self._confidences), 3) if self._confidences else None,
            detection_count=self._detection_count,
            missed_detection_count=self._fn,
            per_class=per_class_out,
            confusion_matrix=self._confusion if self.method == "box_iou" else None,
        )
