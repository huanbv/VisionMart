# ADR-009 — ByteTrack as the multi-object tracker

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

Detection alone (ADR-008) only tells us *what* is in a frame. To compute
queues, dwell time, journeys, and "this is the same shopper across two
frames" we need a **multi-object tracker** that maintains stable IDs over
time. The tracker must:

- Handle 30 FPS streams with low compute overhead (we already pay for the
  detector).
- Survive short occlusions (a shopper walking behind a shelf for ~2 s).
- Work with the detector outputs we already produce (bounding boxes +
  confidence), without requiring a separate appearance model on every frame.
- Be free of restrictive licensing.

## Decision

Adopt **ByteTrack** as the default multi-object tracker.

- ByteTrack consumes the per-frame detection output from YOLOv8 (ADR-008) and
  emits track IDs.
- It works on detection scores alone — no separate Re-ID model required for
  basic tracking. We add a Re-ID model later (story `VM-AI-CUST-01`) only for
  cross-camera re-identification.
- The implementation is wrapped behind a small `Tracker` interface so we can
  swap in alternatives per camera or per pipeline.

## Consequences

**Positive**

- Excellent accuracy-per-FLOP for crowded scenes — exactly the retail
  setting.
- Minimal added latency on top of the detector.
- MIT license; no AGPL concerns.
- Works out of the box with any detector that emits `(bbox, score, class)`,
  including the YOLOv8 we already run.

**Negative**

- ID-switch rate degrades under long occlusions or low frame rates. Mitigated
  by combining with a Re-ID model on high-value pipelines (smart cart, loss
  prevention).
- Hyper-parameters (track buffer, match thresholds) need per-camera tuning;
  we expose them in the per-camera AI configuration (story `VM-CAM-04`).

**Neutral**

- The decision is bounded to "the default tracker." Particular pipelines may
  opt into more advanced trackers (e.g. BoT-SORT, StrongSORT) when their
  cost is justified.

## Alternatives Considered

- **SORT / DeepSORT** — Older, weaker on crowded scenes. Rejected as
  default.
- **BoT-SORT / StrongSORT** — Slightly higher accuracy with a heavier
  appearance model on every frame; reconsider for premium pipelines.
- **OC-SORT** — Comparable; ByteTrack's broader community and tooling won.
- **A managed tracking service** — None offer the on-premise + per-frame
  control we need. Rejected.
