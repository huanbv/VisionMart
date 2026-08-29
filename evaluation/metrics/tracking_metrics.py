"""Tracking stability metrics, computed from a sequence of ByteTrack ID
sets observed frame-by-frame on ONE video/camera run.

Honesty note on "ID switches": a true ID switch (tracker silently hands
one object's identity to a different object) can only be measured by
comparing tracked IDs against ground-truth object identity across frames
(MOT-style trajectory annotations). This repo has no such annotations
anywhere (see `evaluation/datasets/annotations.py` — its ground truth is
per-frame boxes/counts, not cross-frame identity). Without that, this
module reports only what's derivable from ID continuity alone:
fragmentation, track lifetime, continuity ratio, and an ID-churn proxy —
and it labels the proxy explicitly as NOT a substitute for a true ID
switch count (this mirrors the caveat already used for the same proxy in
`ai-engine/scripts/sprint1_evaluation.py`). If the caller supplies
`gt_identity_map`, true ID switches ARE computed; otherwise that field is
`None` with a stated reason.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class TrackingMetricsResult:
    frame_count: int
    unique_track_ids: int
    avg_track_length_frames: float | None
    min_track_length_frames: int | None
    max_track_length_frames: int | None
    avg_track_continuity: float | None  # mean(appearances / span) across ids, 1.0 = never dropped mid-track
    fragmentation_count: int            # total "disappear then reappear" events across all ids
    lost_track_events: int              # ids whose last appearance is >= gap_threshold frames before sequence end
    id_churn_proxy: float | None        # mean fraction of ids that changed between consecutive frames
    id_switch_count: int | None
    id_switch_reason: str
    re_id_implemented: bool
    re_id_reason: str


class TrackingMetricsCollector:
    """Call `observe(frame_index, track_ids)` once per frame, in order, for
    a single continuous video run (do not mix frames from different
    videos/cameras into one collector instance)."""

    def __init__(self, gap_threshold_frames: int = 15) -> None:
        self.gap_threshold_frames = gap_threshold_frames
        self._frame_ids: list[tuple[int, set[int]]] = []

    def observe(self, frame_index: int, track_ids: set[int]) -> None:
        self._frame_ids.append((frame_index, set(track_ids)))

    def summary(self, gt_identity_map: dict[int, dict[int, str]] | None = None) -> TrackingMetricsResult:
        if not self._frame_ids:
            return TrackingMetricsResult(
                frame_count=0, unique_track_ids=0, avg_track_length_frames=None,
                min_track_length_frames=None, max_track_length_frames=None,
                avg_track_continuity=None, fragmentation_count=0, lost_track_events=0,
                id_churn_proxy=None, id_switch_count=None,
                id_switch_reason="No frames observed.",
                re_id_implemented=False,
                re_id_reason="No frames observed.",
            )

        self._frame_ids.sort(key=lambda t: t[0])
        frame_indices = [f for f, _ in self._frame_ids]
        last_frame = frame_indices[-1]

        appearances: dict[int, list[int]] = {}
        for f, ids in self._frame_ids:
            for tid in ids:
                appearances.setdefault(tid, []).append(f)

        lengths, continuities = [], []
        fragmentation_count = 0
        lost_track_events = 0
        for tid, frames in appearances.items():
            frames.sort()
            lengths.append(len(frames))
            span = frames[-1] - frames[0] + 1
            continuities.append(len(frames) / span if span > 0 else 1.0)
            # Fragmentation: count gaps (missing frame indices between two
            # consecutive appearances of this id).
            gaps = 0
            for i in range(1, len(frames)):
                if frames[i] - frames[i - 1] > 1:
                    gaps += 1
            fragmentation_count += gaps
            # Lost track: this id's trajectory ends well before the
            # sequence's last observed frame — heuristic signal for
            # "occluded/lost" rather than "subject naturally left frame at
            # the end of the recording"; not a certainty either way without
            # scene-level ground truth.
            if (last_frame - frames[-1]) >= self.gap_threshold_frames:
                lost_track_events += 1

        churns = []
        for i in range(1, len(self._frame_ids)):
            prev_ids = self._frame_ids[i - 1][1]
            cur_ids = self._frame_ids[i][1]
            union = prev_ids | cur_ids
            if union:
                churns.append(len(prev_ids ^ cur_ids) / len(union))

        id_switch_count = None
        id_switch_reason = (
            "Not measured: computing a true ID-switch count requires ground-truth "
            "object identity tracked across frames (MOT-style trajectory annotations), "
            "which were not supplied to this run (gt_identity_map=None). The "
            "id_churn_proxy field below is a rough continuity signal, not a substitute."
        )
        if gt_identity_map:
            switches = 0
            prev_track_to_gt: dict[int, str] = {}
            for f, ids in self._frame_ids:
                gt_map = gt_identity_map.get(f, {})
                current_track_to_gt = {tid: gt_map[tid] for tid in ids if tid in gt_map}
                for tid, gt_id in current_track_to_gt.items():
                    if tid in prev_track_to_gt and prev_track_to_gt[tid] != gt_id:
                        switches += 1
                prev_track_to_gt.update(current_track_to_gt)
            id_switch_count = switches
            id_switch_reason = "Measured from supplied gt_identity_map (track_id -> ground-truth object id, per frame)."

        return TrackingMetricsResult(
            frame_count=len(self._frame_ids),
            unique_track_ids=len(appearances),
            avg_track_length_frames=round(statistics.mean(lengths), 2) if lengths else None,
            min_track_length_frames=min(lengths) if lengths else None,
            max_track_length_frames=max(lengths) if lengths else None,
            avg_track_continuity=round(statistics.mean(continuities), 3) if continuities else None,
            fragmentation_count=fragmentation_count,
            lost_track_events=lost_track_events,
            id_churn_proxy=round(statistics.mean(churns), 3) if churns else None,
            id_switch_count=id_switch_count,
            id_switch_reason=id_switch_reason,
            re_id_implemented=False,
            re_id_reason=(
                "Not implemented in ai-engine/app/services/person_tracker.py — there is no "
                "re-identification model or cross-camera appearance matching in the current "
                "system (ByteTrack only re-associates within a single camera's continuous "
                "stream). Re-ID stats are therefore not applicable, not just unmeasured."
            ),
        )
