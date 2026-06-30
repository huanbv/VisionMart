# VisionMart — AI Detection Engine, Tracking & Business Rules

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/20_AI_OVERVIEW.md`
> **Owner:** Lead AI System Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** AI system **design** only. No code, no APIs, no model
> training details, no DDL. Where this document conflicts with
> implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract §2.2](ARCHITECTURE_CONTRACT.md#22-ai-engine-isolation) ·
> [Domain Model](DOMAIN_MODEL.md) ·
> [System Design — AI Pipeline](SYSTEM_DESIGN.md) ·
> [Camera Manager](21_CAMERA_MANAGER.md) ·
> [Authentication — AI Security](13_AUTHENTICATION.md#ai-security-model) ·
> [ADR-008 YOLOv8](adr/ADR-008-yolov8.md) ·
> [ADR-009 ByteTrack](adr/ADR-009-bytetrack.md)

---

# AI System Overview

The VisionMart AI Engine is the **sensor-to-signal** layer of the
platform. It converts raw camera frames into **business-meaningful
events** that the backend can act upon. It is a *separate service*
([ADR-008](adr/ADR-008-yolov8.md)) and follows the cardinal rule:

> **AI proposes; backend decides.** The AI Engine never writes to
> business tables. It emits **events**; the backend validates them and
> orchestrates state changes (Architecture Contract §2.2; BR-28).

### End-to-end pipeline (per camera)

```
[Camera Frames]
        │
        ▼
[Preprocessing]              ── normalise, resize, ROI
        │
        ▼
[YOLOv8 Detection]           ── object + class + bbox + confidence
        │
        ▼
[Object Classification]      ── refines class (e.g. product subcategory)
        │
        ▼
[ByteTrack Tracking]         ── per-camera persistent track_id
        │
        ▼
[Identity Association]       ── customer (with consent), product, employee
        │
        ▼
[Business Rule Engine]       ── stable, debounced, threshold-checked
        │
        ▼
[Event Generation]           ── AIEvent payloads with confidence + provenance
        │
        ▼
[Backend (AI Event Gateway)] ── validates, persists, orchestrates
```

### Layer responsibilities at a glance

| Layer | Owns | Does NOT own |
|-------|------|--------------|
| **Preprocessing** | Decoding, colour, resize, ROI, normalisation. | Business semantics. |
| **Detection** | Where is something in the frame? What class? | Identity, history, decisions. |
| **Classification** | Refined class (e.g. brand/variant). | Decisions. |
| **Tracking** | Per-camera identity across frames. | Cross-camera identity, business identity. |
| **Identity Association** | Mapping a track to `customer_id`, `product_id`, or `employee_id`. | Persisting them — the backend persists. |
| **Rule Engine** | Confidence + debounce + corroboration → an *intent* event. | Writing inventory, cart, or order state. |
| **Event Publisher** | Delivery to the backend with ordering and idempotency keys. | Retrying forever. |
| **Backend** | Decision-making, state mutation, audit. | Knowing which YOLO model was used. |

### Design pillars

| # | Pillar | Translation |
|---|--------|-------------|
| 1 | **Recall at detection, precision at the rule engine** | Detector keeps low thresholds; rules use high thresholds + corroboration. |
| 2 | **Per-camera workers, per-GPU batchers** | Predictable parallelism, isolated failure domains. |
| 3 | **Stateless workers, stateful caches** | Worker state lives in Redis windows and per-camera memory; the AI Engine itself is restartable at any time. |
| 4 | **Bounded everything** | Bounded queues, bounded buffers, bounded event spool. Drops over backups. |
| 5 | **Privacy by default** | No face recognition without active customer consent (BR-22, BR-23). |
| 6 | **Observable everywhere** | Per-stage latency, per-camera drops, per-event-type counters, per-model accuracy proxies. |
| 7 | **Pluggable models** | YOLOv8 today; future detectors swap in via a model registry without changing the rule layer. |

---

# Detection Layer

### Detection models (conceptual)

- **Object detector** — a YOLOv8-class model
  ([ADR-008](adr/ADR-008-yolov8.md)) producing
  `[(class, bbox, confidence), …]` per frame.
- **Classifier refinement** — optional secondary classifier that
  refines a generic class (e.g. "bottle") into a catalogue match
  (e.g. specific SKU / variant) using the bbox crop.
- **Recognition models** (optional, per pipeline) — face embedding
  model, product embedding model.
- All models are **versioned** and registered in a `ModelRegistration`
  per pipeline; only one active version per pipeline at a time
  (Camera Manager §AI Input).

### Object categories (canonical taxonomy)

| Category | Sub-classes (illustrative) | Used by |
|----------|----------------------------|---------|
| `person` | shopper, employee (post-association) | Tracking, customer recognition, theft, queue |
| `product` | per catalogue category / brand | Smart cart, inventory, recognition |
| `shelf` | shelf bay, shelf row | Inventory (out-of-stock), heatmap zones |
| `cart` | physical cart, basket | Cart association, queue |
| `hand` / `hand_interaction` | reach-in, pick-up, return, swap | Smart cart, theft |
| `bag` / `personal_item` | shopping bag, backpack | Theft heuristics |
| `checkout_zone_marker` (virtual) | derived from camera ROI | Queue, conversion |
| `motion` (virtual class) | derived from frame deltas | Heatmap, after-hours alerts |

> Categories are deliberately *visual*. Business-level concepts
> (a *suspicious shopper*, a *paid cart*) are computed downstream in
> the rule engine and the backend.

### Confidence threshold strategy

VisionMart applies **two-stage thresholding**:

1. **Detector-stage threshold** (low; recall-first).
   - Default: detections below ~0.30 are dropped at the detector to
     keep payloads small and inference cheap.
   - Tunable per camera and per class.
2. **Rule-stage threshold** (high; precision-first; per
   [Business Rule BR-26](DOMAIN_MODEL.md#business-rules)).
   - `ProductRecognized` for auto-cart add: **≥ 0.85** *and* stable
     across ≥ 3 frames.
   - `CustomerDetected` (face): **≥ 0.90**.
   - `TheftDetected`: **≥ 0.80** *and* corroborating signals (motion,
     concealment heuristic, exit without checkout).
   - `QueueDetected`: persistence-based — `n_people ≥ k` for
     `duration ≥ t` in a checkout zone.
   - `ShelfBecameEmpty`: shelf occupancy below a per-shelf floor
     for ≥ a configurable window.

### False positive handling

- **Temporal debouncing.** A detection must persist across multiple
  frames before becoming a rule-stage candidate.
- **Spatial gating.** Detections outside the configured ROI for that
  pipeline are dropped.
- **Geometric sanity.** Bbox size and aspect ratio must be within
  per-class bounds (e.g. a "person" bbox the size of 4 % of the frame
  in a top-down camera is rejected).
- **Cross-class arbitration.** If two classes contend for the same
  bbox, the higher-confidence one wins; ties go to the priority
  table (e.g. `person` > `bag`).
- **Negative-mining feedback loop.** Operators can flag a stored
  snapshot as a false positive; flagged samples enter the
  training-data governance pipeline (with consent rules) for the
  next model release.

---

# Tracking System

### Choice of tracker

VisionMart uses **ByteTrack** ([ADR-009](adr/ADR-009-bytetrack.md)) for
per-camera multi-object tracking. ByteTrack uses both high- and low-
confidence detections to maintain identity through partial occlusion
while keeping CPU cost modest.

### Track lifecycle

```
new detection (no match)
        │
        ▼
[tentative]  (waiting for confirmation in next k frames)
        │
        ▼
[confirmed]  → emits TrackingSessionStarted
        │
        ├─ matched on each frame → identity persists
        │
        ├─ unmatched for n frames (occlusion budget) → [lost]
        │       │
        │       ├─ rematched → returns to confirmed
        │       └─ unmatched for > max_lost → [terminated]
        │
        └─ terminated → emits TrackingSessionEnded
```

### Track initialisation

- A `track_id` is allocated per camera, monotonically increasing,
  never reused within the camera's lifetime.
- A track is **confirmed** only after `k` consecutive matched
  detections (default `k = 3`) — this avoids transient flicker
  becoming a phantom shopper.

### Track termination

- A track terminates after `max_lost_frames` of consecutive missed
  matches (default ~30 frames at 5 fps → ~6 seconds).
- A track is also terminated if its detections leave the camera's ROI
  for more than a short grace window.
- Termination produces a `TrackingSessionEnded` event with the final
  duration, the path bbox history (downsampled), and any associated
  identity.

### Occlusion handling

- ByteTrack's two-pass association (high-confidence first, then
  rescue with low-confidence detections) preserves identity through
  short occlusions.
- A bounded **occlusion budget** is configured per pipeline; budgets
  for *person* tracks (~1 s) are larger than for *hand* tracks
  (~0.3 s).
- During the occlusion window the track is in state **`lost`** but
  not yet terminated; it remains eligible for re-match.

### Identity persistence across frames (per camera)

- Per-camera identity is **strong**: the same shopper keeps the same
  `track_id` as long as the tracker can follow them.
- A new appearance after termination is a **new `track_id`**, even if
  it is visually the same person. Re-identification (below) bridges
  this in higher pipelines, not in the tracker.

### Cross-camera tracking

- Cross-camera **re-identification** is a v2 feature (see Future
  Improvements). v1 treats each camera independently.
- Branch-wide identity is reconstructed at the **backend / analytics
  layer** by joining tracks via consented customer recognition or
  cart association, not by the tracker.

---

# Customer Recognition (optional layer)

### Identification strategy

- **Anonymous-by-default.** A shopper is a `track_id` and a set of
  visual attributes; no PII is implied.
- **Opt-in customer recognition.** When a tenant enables face
  recognition *and* a customer has **active consent** for
  `FACE_RECOGNITION`, the engine attempts to match the shopper's face
  embedding against the tenant's enrolled embeddings (BR-22, BR-23).
- A successful match attaches `customer_id` to the
  `TrackingSession` and emits `CustomerDetected`. Failed matches are
  **not stored** as embeddings; they remain anonymous.

### Anonymous tracking fallback

- When consent is absent or face recognition is disabled, every
  shopper remains anonymous for the engine's lifetime of the session.
- Anonymous tracks still feed all analytics that do not require
  identity (footfall, dwell, conversion, heatmap, queue).
- Smart-cart features that need identity (loyalty add-ons,
  personalised promotions) are simply **not offered** for anonymous
  sessions.

### Re-identification (within a session, single camera)

- Inside a single tracking session, identity persists by track. If
  the tracker terminates a track and a new one starts a few seconds
  later in the same area, the engine **MAY** propose a re-attachment
  using soft cues (visual descriptor + spatio-temporal proximity),
  always with a low-confidence flag and never used for sensitive
  actions.

### Privacy constraints

- **Face embedding storage.** Embeddings live in MinIO under tenant-
  segregated buckets; the engine accesses them only via backend-
  issued, short-lived, single-customer-scoped signed URLs.
- **Consent gating.** Recognition is performed **only** when an
  active `CustomerConsent` row exists for the scope
  `FACE_RECOGNITION`. Withdrawal triggers backend-led deletion of
  the embedding and an engine cache invalidation.
- **No covert enrolment.** The engine does not auto-enrol shoppers
  it sees; enrolment is an explicit operator action.
- **No cross-tenant matching.** An embedding belonging to Tenant A is
  not used to identify a shopper in Tenant B even if the engine
  process is shared.

---

# Product Recognition

### Detection vs recognition

- **Detection** answers "is there a product-shaped object here?".
- **Recognition** answers "which SKU is it?". Recognition is an
  embedding-similarity step against the tenant's catalogue index.

### Product detection approach

- A product-aware YOLOv8 head detects product bboxes in shelf,
  shopper-hand, and cart regions.
- Bboxes are passed to the recognition step with their crop and the
  context (shelf id, zone id).

### Product classification strategy

- The recognition step computes an **embedding** for the crop and
  queries the tenant's **catalogue embedding index** (per
  organization, refreshed when products change).
- The result is **top-K matches with similarity scores**. The rule
  engine accepts a match only when:
  - Top-1 similarity ≥ threshold (`0.85` default), and
  - The margin between top-1 and top-2 ≥ a separation threshold
    (defends against confusable SKUs).
- Confusable SKUs flagged in catalogue metadata require
  **additional corroboration** (barcode read from a separate camera
  or a higher persistence requirement).

### Shelf mapping logic

- Each shelf is mapped to a `Zone` and a **planogram** that lists
  expected SKUs in each region.
- The recognition step uses the planogram as a **strong prior**:
  matches that contradict the planogram are downweighted and emit a
  `PlanogramMismatch` signal for the operator.
- Out-of-stock is detected as **persistent shelf-region emptiness**
  rather than as the absence of a particular SKU, which avoids
  false negatives when the camera angle hides a single facing.

### Product position estimation

- The bbox + camera calibration gives an approximate physical
  position (X, Y on the shelf plane).
- Position estimates feed:
  - `ShelfBecameEmpty` (zone-level).
  - Heatmap of product interactions (which products attract reach
    events).
  - `ProductMisplaced` (a product detected outside its planogram
    region for a sustained window).

---

# Business Rule Engine

### Purpose

The rule engine sits **between** the perception stack and the event
publisher. It is the *only* layer in the AI Engine that has a vote on
"this looks like a business event". Detection and tracking are
deliberately rule-free.

### How rules consume signals

A rule reads:

- The latest detections for its camera(s) and class(es).
- The current and recently-closed `TrackingSession`s.
- The associated `customer_id` (if any), `product_id` (if any),
  `employee_id` (if any).
- The zone metadata (`checkout`, `aisle`, `shelf`, `entry`, `exit`).
- The previous output of the rule (for debouncing / hysteresis).

Each rule outputs **at most one event candidate per evaluation**.
Candidates are then passed through deduplication and confidence
filters before publication.

### Core rule families (canonical set)

#### Smart cart rules

- **Pick-up rule.** Hand-interaction event near a shelf region for a
  product class, followed by the product appearing in or near a
  cart/basket for ≥ `t_persist` (default ~1 s) → emit
  `ProductPickedUp` and `ProductRecognized` (if recognition succeeds).
- **Return rule.** Inverse of pick-up: product seen leaving cart and
  re-entering shelf region → emit `ProductReturned`.
- **Swap rule.** Hand interaction places a different SKU back than
  the one removed within a short window → emit `ProductSwapped`
  (low-confidence; informational).

#### Checkout & exit rules

- **Queue rule.** ≥ `k` persons in a configured `checkout` zone for
  ≥ `t_queue` (default ~30 s) → emit `QueueDetected` with estimated
  wait.
- **Cart-not-paid-on-exit rule.** A `TrackingSession` that contained
  pick-ups but no checkout association reaches the exit zone → emit
  `TheftSuspected` (informational only; *not* `TheftDetected`).
- **TheftDetected rule.** `TheftSuspected` + corroborating cue
  (concealment, evasion, alarm pad bypass) → emit `TheftDetected`
  (high-severity).

#### Inventory rules

- **Shelf-empty rule.** Shelf-region occupancy below the per-shelf
  floor for ≥ `t_empty` (default ~30 s) → emit `ShelfBecameEmpty`.
- **Restock rule.** Shelf-region occupancy recovers above floor for
  ≥ `t_restock` → emit `ShelfRestocked`.
- **Planogram mismatch rule.** Detected SKU outside its planogram
  region for ≥ `t_misplaced` → emit `PlanogramMismatch`.

#### Customer & analytics rules

- **Customer detected rule.** Face match succeeds for an enrolled
  customer with active consent and confidence ≥ 0.90 → emit
  `CustomerDetected` (rate-limited to once per session).
- **Dwell rule.** `TrackingSession` stays inside a zone for ≥
  `t_dwell` → contributes to dwell aggregates (no event per dwell;
  aggregated upstream).
- **Heatmap rule.** Periodic tile updates are computed from active
  tracks; an aggregated `HeatmapUpdated` event is emitted at a
  bounded cadence (e.g. once per minute per camera).
- **Conversion rule.** Track that enters with `pick-up` events and
  is later associated to a paid order via backend correlation
  contributes to the conversion aggregate.

### Rule evaluation model

- Rules are **declarative configurations** (per camera, per pipeline)
  with parameters such as `threshold`, `persistence_frames`,
  `cooldown_seconds`, `zone_id`. They are not arbitrary scripts.
- The rule engine evaluates **per frame** for fast-reacting rules and
  **per tick** (e.g. every second) for slow rules (queue, heatmap).
- Each rule maintains a **bounded per-camera state** in memory plus
  a Redis-backed snapshot so a worker restart loses at most a few
  seconds of state.

### Debounce and cooldown

- **Persistence requirement.** No event is emitted until the
  underlying signal has persisted for at least its configured number
  of frames or seconds.
- **Cooldown.** After emitting an event, the same rule cannot
  re-emit for the same `(track_id, product_id)` for at least
  `cooldown_seconds`. This is the primary defence against duplicate
  events.

### Operator override

- Each rule is **enableable / disableable per camera** without
  redeploying the engine; toggles live in `CameraAIConfig`.
- Each rule's parameters are tunable within a platform-defined
  envelope (no rule can be tuned into a security-bypassing
  configuration).

---

# Event System

### Output events (canonical catalogue produced by the AI Engine)

| Event | Source rule | Cardinality (typical) | Severity |
|-------|-------------|------------------------|----------|
| `CustomerDetected` | Customer detected rule | once per session per customer | Info |
| `ObjectDetected` *(internal only)* | Detection layer | per detection | Internal (not published) |
| `ProductDetected` *(internal)* | Recognition layer | per recognition | Internal |
| `ProductPickedUp` | Pick-up rule | per pick-up | Info |
| `ProductReturned` | Return rule | per return | Info |
| `ProductSwapped` | Swap rule | rare | Info |
| `CartUpdated` *(by backend)* | n/a — emitted by backend after deciding on a pick-up event | per change | Info |
| `InventoryUpdated` *(by backend)* | n/a — backend decides | per change | Info |
| `ShelfBecameEmpty` | Shelf-empty rule | sparse | Warning |
| `ShelfRestocked` | Restock rule | sparse | Info |
| `PlanogramMismatch` | Planogram rule | sparse | Warning |
| `QueueDetected` | Queue rule | rate-limited | Warning |
| `HeatmapUpdated` | Heatmap rule | periodic | Info |
| `MotionDetected` | Motion (afterhours) rule | sparse | Warning |
| `TheftSuspected` | Cart-not-paid-on-exit rule | sparse | Warning |
| `TheftDetected` | Theft rule | rare | High |
| `TrackingSessionStarted` / `Ended` | Tracker | per session | Internal/Analytics |
| `SnapshotCaptured` | When evidence is needed | per snapshot | Info |
| `ModelDeployed` *(by backend)* | Model registry | per deployment | Info |

> Events that begin "Cart…" or "Inventory…" or "Order…" are **always
> emitted by the backend** in response to AI proposals; the AI Engine
> does not emit them directly. This preserves the "AI proposes;
> backend decides" rule.

### Event creation logic

A rule that fires builds an event candidate with:

- `event_type` (versioned: e.g. `ProductPickedUp@v1`).
- `event_id` (UUID; **idempotency key**).
- `occurred_at` (UTC timestamp from frame capture, not wall-clock at
  publish).
- `camera_id`, `branch_id`, `organization_id`.
- `tracking_session_id` (when applicable).
- `payload` (structured per event type: product/customer ids,
  confidences, bbox excerpts, zone id, etc.).
- `confidence` (the rule's combined score).
- `correlation_id` (the ingestion correlation id for the frame, so
  the same end-to-end thread can be traced through logs).
- Optional `snapshot_ref` for evidence-bearing events.

### Event enrichment

- The engine enriches detections with **catalogue context** (product
  name, category) only when needed; the backend can always re-resolve
  from `product_id`.
- The engine **does not** enrich with customer PII; only
  `customer_id` is sent.
- Enrichment fields are clearly marked as **denormalised hints** —
  the backend treats `product_id` and `customer_id` as authoritative.

### Event filtering

- **Threshold filter.** Below the rule-stage threshold → dropped.
- **ROI / zone filter.** Outside configured zone → dropped.
- **Severity floor.** A pipeline can be configured to publish only
  events at or above a severity (e.g. cost-sensitive deployments
  drop `Info`).
- **Tenant kill-switch.** A tenant can globally disable any event
  type without redeployment.

### Event deduplication

- The engine maintains a small **sliding window** of recently-emitted
  `(event_type, track_id, product_id)` tuples per camera and refuses
  re-emission within the rule's cooldown.
- The publisher carries `event_id`; duplicates from publisher
  retries are safe because the backend dedupes on this id.
- For **periodic** events (heatmap, queue), the engine emits at a
  bounded cadence by design — there is no need for sliding-window
  dedupe.

---

# State Management

### What state lives where

| State | Where | Lifetime |
|-------|-------|----------|
| **Per-frame detections** | Worker memory | One frame |
| **Active tracks (per camera)** | Worker memory + small Redis snapshot | Seconds–minutes |
| **Rule state (per camera, per rule)** | Worker memory + Redis snapshot | Until rule reset |
| **Recent event history (per camera)** | Redis (`ai:events:recent:{cameraId}`) | Minutes |
| **Catalogue embedding index (per tenant)** | Worker memory, refreshed on signal | Until catalogue change |
| **Face embedding cache (per consenting customer)** | Worker memory, LRU-bounded | Short; flushed on consent withdrawal |
| **Snapshots (evidence)** | MinIO | Per retention policy |
| **Configuration (camera, pipelines, models)** | Backend Postgres, pulled at start | Until config change |
| **Pipeline metrics** | Prometheus | Per metric retention |

### Track ↔ Session mapping

- The tracker assigns a `track_id`; the engine wraps it in a
  `TrackingSession` object that carries metadata (start time,
  customer association if any, attributes).
- `TrackingSession` ids are UUIDs minted by the engine and persisted
  in the backend's `TrackingSession` table (Camera Manager §AI Input).
- The mapping `(camera_id, track_id) → tracking_session_id` lives in
  Redis with a short TTL and is rebuilt on worker restart from the
  most recent backend record.

### Customer ↔ Cart association

- The engine **proposes** associations
  (`customer_id` ↔ `cart_id`) by combining:
  - Customer recognition events (when consented).
  - Spatio-temporal proximity to a cart bbox.
  - Operator-provided cues (cashier scans a loyalty code).
- The **backend** owns the association: it creates / updates the
  `ShoppingCart` and links to `customer_id`. The engine never writes
  the cart table directly.

### Short-term memory strategy

- The engine keeps a **bounded** recent-events buffer per camera
  (last ~60 s) for rule corroboration (e.g. "did we already see a
  matching pick-up nearby?").
- Older history lives in the backend (`AIEvent`, `DetectionResult`
  partitions); the engine queries the backend only for rare,
  expensive operations (e.g. forensic re-run).

### Redis vs in-memory usage

| Use | Redis | In-memory |
|-----|-------|-----------|
| Hot per-frame state (tracks, rule debounce) | snapshot only | primary |
| Cross-worker coordination (e.g. handoff, cooldown across replicas) | primary | — |
| Catalogue / embedding caches | warm refresh signal | primary |
| Recently emitted events for dedupe | primary | mirror |
| Camera heartbeat for dashboards | primary | — |

> The engine is **stateless across deployments**: kill any worker; it
> rebuilds working state in seconds from Redis + the backend config.

---

# Real-time Processing

### Latency targets (per camera, p95)

| Stage | Budget |
|-------|--------|
| Decode + frame extraction | ≤ 80 ms |
| Preprocessing | ≤ 20 ms |
| YOLOv8 (GPU) | ≤ 40 ms |
| Tracking + identity association | ≤ 50 ms |
| Rule engine + event build | ≤ 30 ms |
| Publish to backend | ≤ 30 ms |
| **End-to-end (camera → AI event accepted by backend)** | **≤ 250 ms** |

CPU-only deployments use a relaxed ≤ 700 ms target and the dashboard
shows an "AI degraded" badge.

### Frame-level processing

- One **per-camera worker** owns ingestion, extraction, tracking,
  rules.
- Frames are processed at the configured **target FPS** (default
  5 fps); raw stream rate is decoupled from inference rate via
  temporal subsampling (Camera Manager §Frame-rate control).

### Stream processing pipeline

- Workers feed a shared **per-GPU detector queue**; results are
  demultiplexed back to the originating worker by frame identity.
- All queues are **bounded**. Drop-from-head is the default policy
  for the frame buffer; for the rule engine's event publish queue,
  drop is paired with metrics and a severity-aware shedding policy
  (low-priority info events drop first).

### Parallel processing strategy

- **Per-camera concurrency** for I/O and tracking.
- **Per-GPU concurrency** for detection (micro-batching across
  cameras).
- **Per-tenant separation** is logical; tenants do not share
  per-camera worker memory but may share GPU nodes.

### GPU utilisation strategy

- Target ~70 % GPU utilisation per node to absorb spikes and
  reconnect storms.
- **Micro-batching** with a small time window (e.g. ≤ 20 ms) — alone
  frames are dispatched without waiting.
- **Heavy pipelines** (face recognition, product recognition with
  large indices) **MAY** be steered onto dedicated GPU pools so
  detection latency is not starved.
- **Inference backends** (CUDA, TensorRT, CPU via ONNX Runtime) are
  selected per deployment; the same model artefact runs on each via
  ONNX.

---

# Error Handling

| Failure | Containment | Recovery |
|---------|-------------|----------|
| **Detector exception (single frame)** | Drop the frame; counter increments. | Next frame proceeds. |
| **Detector OOM** | Shrink batch; if persistent, GPU is taken out of scheduling. | Worker restart; scheduler reroutes cameras. |
| **Tracker corruption** | Reset tracker state for that camera; all current tracks terminate with a `Reset` reason. | New tracks initialise from next frame. |
| **Embedding index out of date** | Recognition falls back to "no match"; events that require recognition simply do not fire. | Backend pushes a refresh signal; engine reloads index. |
| **Face embedding cache miss** | Mark recognition `not_attempted`; event downgrades to anonymous. | Cache warms on next signal. |
| **Frame corruption** | Skip frame; counter increments; if persistent, mark camera `degraded`. | Operator notified; camera replaced or reconfigured. |
| **Rule misconfiguration** | A rule that throws is **disabled** for the camera and reported. | Operator fixes config; rule re-enabled. |
| **Snapshot upload failure** | Spool locally with bounded disk; event is published with `snapshot_pending=true`. | On recovery, spool flushes; backend reconciles snapshot refs. |
| **Event publish failure** | Bounded retry; bounded local spool; further drops with metrics and severity-aware shedding. | When backend recovers, the engine resumes — old events are accepted as lost (real-time bias). |
| **Model loaded with wrong version** | Engine refuses to start the affected pipeline; status `error`. | Operator activates correct `ModelRegistration`; engine reloads. |
| **Clock skew** | Events flagged; rule engine refuses frame timestamps drifting beyond budget. | NTP corrected; alert. |

### Cardinal rule

- **No AI failure may corrupt business state.** AI is *advisory*. If
  the engine is down, the dashboard shows "AI unavailable"; manual
  operations continue; financial state remains correct.

---

# Scalability Design

### Multi-camera load distribution

- Cameras are assigned to engine nodes by **consistent hashing** on
  `camera_id`. Failover redistributes only the affected slice.
- A scheduler tracks per-node CPU, GPU, memory, in-flight batches,
  and event publish latency, and rebalances when a node exceeds its
  envelope.

### Multi-GPU scaling

- The detector runs on multiple GPUs as **independent batchers**.
  Cameras are bound to a GPU at assignment time; per-GPU queues
  guarantee predictable latency.
- Heavy pipelines run on **dedicated GPU pools** when configured.

### Horizontal AI service scaling

- The engine deploys as a set of identical workers behind a control
  plane that:
  - Pulls camera assignments from the backend.
  - Reports health and metrics.
  - Receives operator commands (enable/disable pipelines, reload
    models).
- On Kubernetes, **KEDA** scales workers based on GPU/CPU usage and
  event-publish queue depth.

### Queue-based processing

- Internal queues between stages are **bounded** and **monitored**.
- The publish queue is **per-event-type** so severity-aware shedding
  is possible without dropping a whole stream of events.
- A growing publish queue is itself a signal that backend ingestion
  is slow; alerts fire before the queue overflows.

---

# Privacy & Ethics

### Data privacy considerations

- **Frames never reach the backend or the SPA.** Only events and
  optional evidence snapshots leave the engine.
- **Snapshots are minimised** — captured only when an event is
  evidence-bearing or operator-requested; lifecycle is per
  documented retention (Camera Manager §Retention).
- **PII is not embedded in events.** Customers are identified by
  `customer_id`; names, phones, emails never travel in the AI
  payload.
- **Tenant segregation is absolute.** No tenant's embeddings, no
  tenant's frames, no tenant's events ever cross to another tenant
  even if the engine binaries are shared.

### Face recognition limitations

- **Off by default.** Tenants opt in per branch.
- **Consent-gated.** A face embedding is matched only for customers
  with active `FACE_RECOGNITION` consent.
- **No covert enrolment.** Enrolment requires an explicit operator
  action that records the actor.
- **Withdrawal honoured promptly.** On consent withdrawal the
  backend purges the embedding and signals the engine; recognition
  for that customer stops at the next refresh.
- **Demographic estimation** (age band, gender) is treated as
  *biometric-adjacent*: disabled by default, opt-in per tenant,
  results stored only as **aggregates**, never per-individual.

### Data retention rules

- **Frames in memory** — milliseconds.
- **Snapshots** — per `purpose` tag (Camera Manager §Retention).
- **Embeddings** — kept until consent withdrawal; tested for staleness
  per tenant policy.
- **AIEvent / DetectionResult** — partitioned and retained per
  Database Design (90 d / 30 d defaults; aggregated before purge).
- **Training samples** — governed by a separate data-governance
  policy outside the runtime engine.

### CCTV / regulatory compliance

- Tenants **MUST** display the required CCTV signage; the platform
  exposes a policy field but does not replace legal counsel.
- Configurable **public-area exclusion zones** mask faces in
  snapshots before storage when required.
- Region-specific options (e.g. GDPR / CCPA / VN PDPL) can be
  enabled per tenant: stricter consent gating, shorter retention,
  data residency.
- Audit logs cover every consent change, every face match, every
  snapshot read, and every model deployment.

### Fairness and model governance

- Models pass a **bias evaluation** before deployment; activation is
  blocked if performance disparities across demographic groups
  exceed a documented threshold.
- An **explainability** record is captured per model version
  (test datasets, evaluation metrics, known limitations) and stored
  with `ModelRegistration`.
- Operators can see, per camera, which model version produced an
  event — supporting post-hoc audits.

---

# Backend Integration

### How AI sends events to backend

- The AI Engine authenticates to the backend as a **service account**
  via an API key scoped to the tenant and the cameras it is
  assigned to ([Authentication §AI Security](13_AUTHENTICATION.md#ai-security-model)).
- Events are delivered to a dedicated **AI Event Gateway** endpoint
  on the backend. The gateway:
  1. Authenticates the caller.
  2. Verifies camera/tenant ownership.
  3. Validates schema, timestamps, confidence ranges.
  4. Persists `AIEvent` (and sampled `DetectionResult`) inside a
     partitioned, indexed write.
  5. Hands the event to the EventBus for application services.

### Event format (conceptual)

A published event contains:

- `event_id` (idempotency key).
- `event_type` (with version: `<Name>@vN`).
- `occurred_at` (UTC; frame capture time).
- `produced_at` (UTC; rule engine emission time).
- `organization_id`, `branch_id`, `camera_id`,
  `tracking_session_id?`.
- `payload` (typed, per event type).
- `confidence` (decimal `0..1`).
- `model_version` (the model that produced the underlying
  perception).
- `correlation_id`.
- `snapshot_ref?` (URI/handle to an evidence snapshot, when
  applicable).

### Communication method

- **Primary:** authenticated HTTPS POST to the AI Event Gateway.
  Simple, secure, easy to debug, easy to scale.
- **Secondary (future):** a message broker (e.g. Redis Streams /
  RabbitMQ / Kafka) for very high event rates. The engine's
  publisher abstracts the transport so a future ADR can switch the
  default without touching rules.
- **Live operator streams** (live tiles, detection overlays) travel
  over a **separate transport** (WebRTC for pixels; WebSocket for
  metadata) — they are *not* events and do not flow through the AI
  Event Gateway.

### Decoupling strategy

- The engine has **no direct DB access**. It writes nothing to
  Postgres directly.
- The engine has **no direct access** to business APIs that mutate
  state (cart, inventory, orders); it can only publish events.
- The backend treats each event as **advisory**: it independently
  re-checks ownership, scope, and invariants before mutating state.
- Schema changes follow **additive** versioning. Old event versions
  continue to be accepted (or deprecated through a documented
  window) so engine rollouts and backend rollouts are independent.

---

# Future Improvements

### Perception

- **3D and depth-aware detection** for richer interaction
  understanding (reach, grasp).
- **Cross-camera re-identification** across cameras within a
  branch, with strict privacy guarantees (on-device descriptors
  only, no central re-ID database).
- **Pose estimation** for fine-grained interaction events
  (concealment, reach into bag).
- **Domain-adapted detectors** per tenant catalogue, distilled and
  versioned through `ModelRegistration`.

### Rules and reasoning

- A small **policy language** for tenant-defined rules (within a
  sandboxed, auditable surface), so operators can express
  retail-specific patterns without code changes.
- **Causal corroboration** across cameras (e.g. shopper seen at
  shelf A + later at exit B without checkout).
- **Anomaly detection** as a feature alongside hand-written rules.

### Deployment and ops

- **On-camera AI** (where supported) to offload detection at the
  source.
- **Edge-to-cloud hybrid** with cloud-only heavy pipelines (e.g.
  large recognition indices) and edge-only sensitive pipelines
  (face matching).
- **A/B model rollout** with shadow inference and automatic
  rollback on regression.
- **Self-tuning pipelines** that propose target_fps and pipeline
  mix per camera based on measured load and accuracy proxies.

### Privacy and ethics

- **On-device face matching** so embeddings never leave the
  branch.
- **Differential-privacy** noise for analytics released to third
  parties.
- **Tamper-evident snapshots** signed at capture time.
- **Right-to-explanation** tooling that, for any event triggered on
  a customer, can reconstruct the chain (model version, frames
  sampled, confidence, rule).

### Anti-goals (deliberately not on the plan)

- Letting the AI Engine write to business tables.
- A single "do everything" model — VisionMart prefers a small,
  composable set of specialised models.
- Long-lived, unbounded buffers anywhere in the engine.
- Covert biometric enrolment.
- Cross-tenant model sharing of any kind that could leak
  catalogues or faces.
- Treating AI output as authoritative for financial state.

---

*This document is the canonical AI Engine design. Any change to the
perception stack, tracking model, rule engine, event catalogue, or
backend integration requires a PR that updates **only this file** (and,
when needed, an ADR explaining the rationale).*
