# VisionMart — Camera Management & Video Pipeline Design

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/21_CAMERA_MANAGER.md`
> **Owner:** Lead AI Infrastructure Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** system **design** only. No code, no APIs, no DDL, no
> framework-specific instructions. Where this document conflicts with
> implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract §2.2](ARCHITECTURE_CONTRACT.md#22-ai-engine-isolation) ·
> [Domain Model — Camera & AI](DOMAIN_MODEL.md) ·
> [System Design — AI Pipeline](SYSTEM_DESIGN.md) ·
> [Authentication](13_AUTHENTICATION.md) ·
> [ADR-008 YOLOv8](adr/ADR-008-yolov8.md) ·
> [ADR-009 ByteTrack](adr/ADR-009-bytetrack.md) ·
> [ADR-011 MinIO](adr/ADR-011-minio.md)

---

# Camera System Overview

VisionMart turns ordinary store cameras into the **sensor layer** of an
AI-driven retail operations platform. The Camera Management & Video
Pipeline subsystem owns everything between the camera lens and the
backend's domain events:

- Registering and configuring cameras.
- Ingesting RTSP / RTSPS streams.
- Extracting frames at a controlled rate.
- Feeding the AI Engine (YOLOv8 + ByteTrack + recognition).
- Generating high-signal AI events and pushing them to the backend.
- Storing evidence (snapshots, short clips) in MinIO when needed.
- Monitoring camera health and reconnecting automatically.

### Design pillars

| # | Pillar | Translation |
|---|--------|-------------|
| 1 | **Frames never enter Postgres or the SPA** | Raw video lives only in the AI Engine's memory or in MinIO. The backend sees *events*, not pixels. |
| 2 | **AI down ≠ retail down** | Camera/AI failure degrades AI features only; POS, inventory, and the dashboard remain operational. |
| 3 | **Backpressure beats buffering** | When AI is slower than ingestion, frames are *dropped*, not queued indefinitely. |
| 4 | **One pipeline per camera, one worker per pipeline** | Predictable resource usage, isolated failure domains. |
| 5 | **Stateless workers, stateful registry** | Workers can be killed and respawned; camera state lives in Postgres + Redis. |
| 6 | **Edge-friendly** | The same engine runs on a Jetson-class device at a branch or on a central GPU node — only configuration changes. |
| 7 | **Audit-grade evidence** | Every event that triggers a business action **MAY** carry a snapshot reference; that snapshot is immutable. |

### Where each component lives

| Component | Process | Default host |
|-----------|---------|--------------|
| Camera registry, configuration, health record | Backend (FastAPI) | Backend host |
| Stream ingestion worker | AI Engine | Edge node or GPU node |
| Frame extractor, preprocessor | AI Engine | Same as ingestion |
| YOLOv8 detector, ByteTrack tracker | AI Engine | GPU node (CPU fallback) |
| Rule engine + event publisher | AI Engine | Same as detector |
| Event consumer, business orchestration | Backend | Backend host |
| Snapshots, clips | MinIO | Object storage tier |
| Hot tracking window, live track state | Redis | Cache tier |

---

# Camera Management Model

### Camera entity (conceptual)

A `Camera` is described by:

- A stable `camera_id` (UUID).
- Tenant + branch scope: `organization_id`, `branch_id`.
- A human-friendly `code` (unique per organization) and `name`.
- A `stream_url` (RTSP / RTSPS) with credentials **stored as a
  reference to a secret**, never inline.
- Geometry: `location` (textual), optional `zone_id` link, optional
  `mounting` metadata (height, FOV, tilt).
- Capture parameters: `resolution`, native `fps`, target capture
  `target_fps`, `codec`.
- Pipeline toggles: which AI pipelines this camera feeds
  (`detection`, `tracking`, `face`, `theft`, `heatmap`, `queue`),
  each with its own parameters.
- Health fields: `status` (`pending`, `online`, `degraded`,
  `offline`, `error`, `disabled`), `last_seen_at`, `last_error`.
- Lifecycle: `is_active`, `installed_at`, audit + soft-delete
  columns.

> See [Database Design](10_DATABASE_DESIGN.md) for the canonical
> `Camera`, `Zone`, `CameraAIConfig`, `VisionPipeline`,
> `ModelRegistration` entities.

### Camera registration flow

```
Admin / Branch Manager UI
        │  fills in: code, name, stream URL, branch, zone, pipelines
        ▼
Backend (validation)
        │  - validates RTSP URL format
        │  - stores credentials in the secret manager
        │  - assigns to branch (RBAC re-check)
        │  - creates Camera row (status=pending)
        ▼
Backend → AI Engine (provisioning event: CameraRegistered)
        │  - AI Engine receives camera definition
        │  - schedules a probe attempt
        ▼
AI Engine (probe)
        │  - opens RTSP stream
        │  - reads N frames to confirm decoding
        │  - measures effective fps, resolution, codec
        ▼
AI Engine → Backend (CameraProbed)
        │  - status → online (or error)
        │  - measured parameters saved
        ▼
Backend
        │  - emits CameraOnline
        │  - notifies branch dashboard
```

### Camera authentication (camera → AI Engine)

- Cameras authenticate to the AI Engine using **per-camera RTSP
  credentials** stored in the secret manager. Credentials are read at
  worker start and held in memory; they are never logged.
- RTSPS (TLS) **SHOULD** be used wherever the camera supports it.
- IP-based allowlist on the camera VLAN (where deployment topology
  permits) restricts which hosts can pull the stream.
- A camera that fails authentication is moved to `error` with a
  reason code; the secret rotation flow is triggered.

### AI Engine ↔ Backend authentication

- The AI Engine authenticates to the backend as a **service account**
  via API key (see [Authentication §AI Security](13_AUTHENTICATION.md#ai-security-model)).
- The key is scoped to:
  - Reading camera assignments for the engine.
  - Publishing AI events for those cameras.
  - Uploading snapshots via backend-issued signed URLs.

### Camera ↔ Branch assignment

- A camera **belongs to exactly one branch** (`branch_id`
  `NOT NULL`) — see [Multi-Branch Security](13_AUTHENTICATION.md#multi-branch-security).
- A camera **MAY** belong to one or more **zones** within that branch
  (entrance, aisle, checkout, stock room). Zones are the smallest
  unit of analytics aggregation.
- Cross-branch camera moves are explicit operations with audit
  (`camera.reassigned`); they do not retroactively rewrite history.

### Status lifecycle

```
        pending ──probe ok──► online
            │                  │
            │                  ├── degraded (drops, fps below target,
            │                  │   reconnects within window)
            │                  │
            │                  └── offline (no frames in window)
            │
            └── error (auth failed, unsupported codec, persistent decode
                error)

  any state ───disable───► disabled (operator action; not auto)
```

State transitions are emitted as domain events
(`CameraOnline`, `CameraDegraded`, `CameraOffline`, `CameraError`,
`CameraDisabled`).

### Camera configuration boundaries

- **Capture configuration** (target FPS, resolution downscale, ROI
  crop) lives on the camera record and is honoured by the AI Engine.
- **Pipeline configuration** (which pipelines run, thresholds) lives
  in `CameraAIConfig`.
- **Operational configuration** (worker pool, GPU node) is **engine-
  side** and is **not** stored in the camera record — operators
  reconfigure deployment without touching tenant data.

---

# Video Ingestion Pipeline

### End-to-end flow (per camera)

```
[Camera (RTSP/RTSPS)]
        │
        ▼
[Stream Handler]              ── one task per camera
        │  decodes container, reads packets, handles
        │  reconnection, surfaces stream metrics
        ▼
[Frame Extractor]
        │  emits frames at target_fps using
        │  deterministic frame sampling (NOT every frame)
        ▼
[Frame Buffer]                ── small, bounded
        │  ring buffer of decoded frames waiting for AI
        │  (typical capacity: ≤ 1 second of frames)
        ▼
[Preprocessor]
        │  letterbox / resize, colour-space conversion,
        │  normalisation, optional ROI crop
        ▼
[AI Processing Queue]         ── per-GPU, prioritised
        │  delivered as batches to the detector
        ▼
[YOLOv8 Detector]
        │
        ▼
[ByteTrack Tracker]
        │
        ▼
[Recognition (optional pipelines)]
        │
        ▼
[Rule Engine] ──► [Event Publisher] ──► [Backend / Redis pub/sub]
```

### Frame-rate control strategy

- Each camera has a **target capture FPS** (default 5 fps; configurable
  by pipeline). The stream itself may deliver 25–30 fps.
- The frame extractor performs **temporal subsampling** so the AI
  receives only the target FPS — the cheapest source of latency and
  cost savings.
- For pipelines that need different rates (e.g. theft detection at
  2 fps, queue counting at 1 fps), the camera produces **one frame
  stream**, and downstream pipelines decide which frames they read
  (no duplicate decoding).

### Buffering strategy

- The frame buffer between extractor and preprocessor is a **bounded
  ring buffer** (≤ 1 second of frames).
- Bounded queues throughout the AI Engine; never `unbounded`.
- When the buffer is full, the **oldest frame is dropped** (drop-from-
  head) and a `frame_dropped` counter increments. Newest frames are
  always preferred for real-time relevance.

### Backpressure handling

- Backpressure is **explicit and observable**:
  - Drop counters per camera per pipeline.
  - Latency percentiles (p50/p95/p99) from capture timestamp to
    detector output.
- Worker policies (in order of escalation):
  1. **Reduce target FPS** automatically when sustained drops exceed
     a threshold.
  2. **Skip lower-priority pipelines** for that camera (e.g. disable
     heatmap, keep theft and queue).
  3. **Open the circuit** — pause the camera's AI for a cooldown
     window; the camera remains *online*, but AI is *degraded*.
  4. **Alert** the operator if degradation persists.

### Loss recovery

- A stream disconnect triggers exponential-backoff reconnects with a
  cap (e.g. 1s → 2s → 5s → 15s → 60s; max ~5 min).
- After reconnect, processing **resumes from now** — historical
  frames are not replayed. Lost video is lost; events that depended
  on the lost window simply do not fire.
- Snapshots captured before the disconnect remain in MinIO.

---

# Frame Processing Architecture

### Real-time vs deferred

- The default path is **real-time**: each frame is preprocessed and
  fed to the detector with the goal of < 250 ms end-to-end latency
  (camera → AI event).
- Deferred / batch paths exist for:
  - **Heatmap roll-ups** — aggregated from streaming detections, not
    re-processed from video.
  - **Forensic re-runs** on stored snapshots when a model is
    upgraded.

### Batch vs streaming inference

- The detector accepts **micro-batches** (typical batch size 4–16
  frames) drawn from **multiple cameras** sharing a GPU.
- Batching is **time-bounded** — a frame waits up to a small
  configurable window for batch-mates and then is dispatched, even if
  alone. This keeps tail latency predictable.
- Tracking and recognition operate **per camera** (no cross-camera
  batching) because they carry per-camera state.

### GPU vs CPU distribution

| Stage | Preferred device | Notes |
|-------|------------------|-------|
| RTSP decode | CPU (or GPU NVDEC where present) | Cheap to parallelise across cores. |
| Preprocessing | CPU (SIMD) | GPU preprocessing acceptable for high-fps cameras. |
| YOLOv8 detection | GPU (CUDA / TensorRT) | CPU fallback via ONNX Runtime for low-budget deployments. |
| ByteTrack | CPU | Lightweight; per-camera state. |
| Face / product recognition | GPU | Batched. |
| Rule engine | CPU | Pure logic. |

### Parallel processing model

- **Per-camera worker** owns ingestion + extraction + tracking + rules
  for one camera. State is local — no shared mutable state across
  cameras for these stages.
- **Per-GPU worker** owns the detector queue for one GPU. Multiple
  per-camera workers feed it; results are demultiplexed by camera
  ID.
- This shape gives independent scaling: add GPU workers for compute,
  add per-camera workers for I/O concurrency.

---

# AI Input Pipeline

### Detailed flow

```
[Frame]
   │  (timestamp, camera_id, frame_id)
   ▼
[Preprocessing]
   │  - colour: BGR → RGB
   │  - resize: letterbox to model input (e.g. 640×640)
   │  - normalisation: [0,1] float
   │  - optional ROI crop (defined per camera/zone)
   ▼
[YOLOv8 Detection]
   │  - micro-batched across cameras
   │  - returns: [{class, confidence, bbox} ...]
   │  - confidence filter at model boundary (e.g. >= 0.30)
   ▼
[ByteTrack Tracking]
   │  - per camera
   │  - assigns/maintains track_id across frames
   │  - opens TrackingSession on first appearance
   │  - closes TrackingSession on max-age miss
   ▼
[Recognition (optional, per pipeline)]
   │  - product recognition: top-K matches against catalogue index
   │  - face embedding lookup (only with active consent)
   │  - returns enriched detections
   ▼
[Rule Engine]
   │  - applies confidence thresholds (BR-26)
   │  - detects domain events (ProductPickedUp,
   │    CustomerDetected, QueueDetected, ...)
   │  - de-duplicates within configured time window
   ▼
[Event Publisher]
   │  - emits AIEvent with payload, confidence,
   │    correlation_id, occurred_at
   │  - persists DetectionResult sample (subsampled)
```

### Frame normalisation

- All cameras' frames are normalised to **the model's input
  dimensions** with letterbox padding to preserve aspect ratio.
- Colour space normalisation is part of preprocessing; cameras with
  unusual colour profiles can carry a per-camera correction
  parameter.

### Inference batching

- The detector waits for **up to N ms** to form a batch, then runs.
- Batches mix cameras; the worker demultiplexes results back to
  per-camera streams by frame identity.
- The batch window is **measured**; under low load, batches of 1 are
  acceptable.

### Tracking sessions

- A `TrackingSession` is opened the first time the tracker assigns a
  new `track_id` for a class of interest.
- The session carries `started_at`, `camera_id`, `object_class`,
  optional `customer_id` (set only when consented recognition
  resolves), and a small JSON attribute bag.
- The session is closed when the tracker has not seen the track for
  a configured grace window (typical 1–3 seconds for shoppers).
- Per-frame `DetectionResult` rows are stored **sampled** (not
  every frame) and reference the session.

### Confidence and threshold rules

- Detector-level threshold is **low** (recall-first).
- Business thresholds are **high** and applied in the rule engine,
  not in the detector (BR-25, BR-26):
  - `ProductRecognized` for auto-cart-add: confidence ≥ **0.85**
    and stable across multiple frames.
  - `CustomerDetected` (face): confidence ≥ **0.90**.
  - `TheftDetected`: confidence ≥ **0.80** **plus** corroboration
    (multiple frames, motion vector heuristics).
- Events below business thresholds may still be **logged** for
  analytics, but **MUST NOT** trigger business state changes.

---

# Video Storage Strategy

### When to store

- **Snapshots (single frames)** are stored when:
  - An `AIEvent` is marked **evidence-bearing** (theft, refund-
    related, audit-triggering).
  - The rule engine detects a **low-confidence but flagged** event
    that an operator should review.
  - An operator manually requests a snapshot.
  - A **training-feedback** sample is collected (with consent and
    anonymisation rules).
- **Short clips (a few seconds, MP4 / fragmented MP4)** are stored
  when:
  - A high-severity incident occurs (theft, safety alert).
  - The operator triggers a clip from the live view.

### When **not** to store

- Continuous 24/7 video recording is **out of scope** for the
  platform. Tenants who need DVR-style recording use a dedicated VMS
  alongside VisionMart.
- Per-frame storage is forbidden — only sampled `DetectionResult`
  metadata enters Postgres.
- Raw RTSP streams **never** persist on the backend host.

### Frame / snapshot storage strategy

- Snapshots are stored in MinIO under a tenant-segregated bucket
  layout:
  - `org/{org_id}/branch/{branch_id}/camera/{camera_id}/snapshots/
    YYYY/MM/DD/{snapshot_id}.jpg`
- Binary data **never** appears in Postgres. The `Snapshot` table
  holds metadata + the MinIO object URI only.
- Snapshots carry a `purpose` tag: `incident`, `audit`, `training`,
  `low_confidence`, `manual`. Lifecycle policies key off the
  purpose.

### Retention policy (defaults; tenant-configurable within bounds)

| Object | Default retention | Notes |
|--------|-------------------|-------|
| Incident snapshots / clips | 1 year hot, then cold archive per regulation | Linked to AuditLog. |
| Audit-triggered snapshots | Match the audit retention. | |
| Low-confidence review samples | 30 days. | Auto-deleted if not actioned. |
| Training samples | Per training-data governance (consent + bias rules). | |
| Manual snapshots | 90 days unless promoted to incident. | |

### Cost optimisation

- Snapshots are stored as **compressed JPEG** with operator-
  configurable quality (default 80).
- Bucket lifecycle rules transition objects to **cheaper tiers** after
  the hot window (e.g. MinIO ILM / S3 Glacier).
- The platform never stores duplicates — snapshot writes are
  content-hashed before upload.

---

# Real-time Streaming Design

### What is streamed to users

| Stream | Source | Cadence | Purpose |
|--------|--------|---------|---------|
| **Live camera tiles** (low-bitrate) | AI Engine forwarder | 5–10 fps, downscaled | Operator dashboard live tiles. |
| **Detection overlays** (bbox metadata) | AI Engine | At AI frame rate | Drawn on top of live tiles. |
| **AI events** | Backend | As they occur | Toast + dashboard updates. |
| **Camera status** | Backend | On change | Tile colour and badges. |
| **Cart sync** (smart cart) | Backend | On change | Per-customer cart UI. |

### Transport

- **Live video tiles** use **WebRTC** (preferred) or **HLS** as a
  fallback. RTSP **never** reaches the browser.
- **AI events + metadata** travel over **WebSocket** (see
  `16_WEBSOCKET.md`) authenticated with the user's JWT.
- The two channels are deliberately separate: video transport is for
  pixels; the WebSocket is for state.

### Topics (conceptual)

- `org.{orgId}.camera.{cameraId}.events` — AI events for one camera.
- `org.{orgId}.branch.{branchId}.cameras.status` — camera lifecycle.
- `org.{orgId}.branch.{branchId}.notifications` — operational alerts.

Topics are **subscribed individually** and each subscribe is
permission-checked at the time of subscription
([Authentication](13_AUTHENTICATION.md#authorization-flow)).

### Latency budget (per-camera, p95)

| Hop | Budget |
|-----|--------|
| Camera → AI Engine (decode + extract) | ≤ 80 ms |
| Preprocessing | ≤ 20 ms |
| YOLOv8 (GPU) | ≤ 40 ms |
| Tracking + recognition + rule | ≤ 50 ms |
| AI Engine → Backend (event publish) | ≤ 30 ms |
| Backend → WebSocket fan-out | ≤ 30 ms |
| **End-to-end (camera → user UI)** | **≤ 250 ms** |

CPU-only deployments have a relaxed target (≤ 700 ms p95) and a
clearly marked "AI degraded" badge if exceeded.

### Live dashboard updates

- Updates are **idempotent on `eventId`** so reconnects/replays do
  not double-count.
- The frontend tracks a **monotonic event offset** per topic and can
  request a small backfill on reconnect to fill gaps.
- WebSocket payloads carry the **minimum** data needed to render —
  bulk detail is fetched on demand by REST.

---

# Camera Health Monitoring

### Heartbeat mechanism

- Each per-camera worker reports a heartbeat to:
  - **Redis** (`cam:health:{cameraId}`) every few seconds — low
    latency for the live dashboard.
  - **Backend** (`Camera.last_seen_at`) at a slower cadence (e.g.
    every 30 s) — durable record across restarts.
- Heartbeats include: target_fps, effective_fps, drop_count, queue
  depth, last_error.

### Stream failure detection

- A worker that fails to read a frame within a configured timeout
  enters a **probe** state, emits `CameraDegraded`, and triggers
  reconnect.
- If reconnects fail beyond the backoff cap, the worker emits
  `CameraOffline` and stays in cooldown.

### Auto-reconnect strategy

- **Exponential backoff with jitter**, capped at ~5 min.
- After a successful reconnect, the worker re-runs the **probe
  sequence** (decode N frames, measure fps) and emits `CameraOnline`
  on success.
- A camera that has flapped repeatedly within a short window is
  quarantined (status `degraded`, longer cooldown) and an alert
  fires.

### Alert system for offline cameras

- `CameraDegraded` and `CameraOffline` emit **Notifications** to
  branch managers + on-call ops via the Notification Center.
- Severity escalates with downtime duration.
- Per-camera and per-branch **denylists** for noisy cameras prevent
  alert fatigue; the underlying state is still recorded.

### Health metrics (Prometheus-style)

- `camera_status{camera_id=...}` gauge (online/degraded/offline).
- `camera_fps_target` / `camera_fps_effective` gauges.
- `camera_frames_dropped_total` counter.
- `camera_reconnects_total` counter.
- `ai_pipeline_latency_seconds` histogram (per pipeline, per
  camera).
- `ai_event_published_total{event_type=...}` counter.

---

# Scalability Plan

### Multiple cameras per branch

- Per-camera workers are independent; scaling to dozens of cameras
  per branch node is bounded by **GPU capacity** for detection and
  **bandwidth** for streaming, not by the engine's architecture.
- A typical edge node (Jetson Orin / mid-range GPU server) handles
  16–32 cameras at 5 fps with the default pipeline mix.

### Hundreds of concurrent streams

- The engine scales **horizontally** by adding GPU nodes.
- Cameras are mapped to nodes by **consistent hashing** on
  `camera_id`. Failover redistributes the affected slice only.
- Per-node target utilisation is kept below ~70 % to absorb spikes
  and reconnect storms.

### GPU load balancing

- A scheduler routes new cameras to the **least-loaded node**
  (CPU%, GPU%, memory, in-flight batches).
- Heavy pipelines (face recognition) **MAY** be steered onto
  dedicated GPU pools so they do not starve detection on shared
  nodes.

### Horizontal scaling of stream processors

- The engine is **stateless across deployments** — camera assignments
  and pipeline configs are pulled from the backend at start-up; live
  state lives in Redis and on the local worker.
- Nodes can be added or removed without restarting cameras on other
  nodes; only the affected slice rebalances.
- On Kubernetes, scaling is driven by **KEDA** on GPU/CPU utilisation
  and event-queue depth.

---

# Failure Handling

| Failure | Detection | Containment | Recovery |
|---------|-----------|-------------|----------|
| **RTSP disconnect** | Read timeout. | Per-camera circuit opens; status → `degraded`. | Exponential-backoff reconnect; probe sequence; status → `online`. |
| **Auth failure on RTSP** | Server error code / handshake fail. | Status → `error`; alert. | Operator rotates / fixes credentials; manual `recheck` action. |
| **Camera firmware bug** (corrupt frames) | Decode errors above threshold. | Skip corrupt frames; if persistent, status → `degraded`. | Operator notified; replace / power-cycle camera. |
| **GPU OOM** | Inference exception. | Worker shrinks batch; if persistent, GPU is taken out of the scheduler. | Restart worker; scheduler reroutes cameras. |
| **AI service down** | Heartbeats stop; events queue drains backend side. | Backend marks affected cameras as `ai_unavailable`; AI-driven features hidden in UI; manual flows continue (BR-28). | AI Engine restarts; backfills no historical events; system resumes from "now". |
| **Frame buffer overflow** | Drop counter spikes. | Drop oldest frames; reduce target_fps; alert. | Backpressure resolves automatically as load drops. |
| **Event queue overflow** | Queue depth alert. | Shed low-priority events first (heatmap, analytics); preserve incident-grade events. | Add consumer capacity; clear backlog. |
| **Backend down** | Publisher cannot deliver. | AI Engine buffers a **bounded** number of events; further events are **dropped** (with metrics). Snapshots still upload to MinIO. | Backend recovers; engine resumes; lost events are accepted as lost (the rule engine is real-time-biased). |
| **MinIO down** | Upload errors. | Snapshots written to a **local spool** with bounded disk usage. | On recovery, spool flushes; events that had pending snapshots gain their URIs retroactively. |
| **Clock skew** | NTP delta exceeded. | Events flagged; rule engine refuses to use frame timestamps that drift beyond budget. | Operator alerted; NTP corrected. |
| **Network partition (branch isolated)** | Loss of backend connectivity from edge. | Local cameras keep processing; events spool locally up to capacity. | On reconnect, events flush; analytics tolerate gaps. |

### Cardinal rule

- A failure in the AI or camera pipeline **MUST NEVER** corrupt
  business state. AI proposes; backend decides; missing AI input
  simply means fewer proposals.

---

# Security Model

### Camera authentication

- Per-camera RTSP credentials in the secret manager; **never** in
  source, logs, or unencrypted environment files.
- TLS (RTSPS) where the camera supports it.
- Camera management endpoints on the camera itself **SHOULD** be
  inaccessible from the public internet — placed on a dedicated VLAN.

### Credential handling

- The camera record stores **only a reference** to the secret entry,
  not the password.
- Secrets rotate without redeploying the engine — workers re-read at
  next restart or on a rotation signal.
- API keys for the AI Engine's backend authentication rotate on the
  same model.

### Branch-level isolation

- A camera always belongs to one branch; permission checks for any
  camera read/write operation re-verify the principal's branch
  scope.
- AI events carrying `camera_id` are validated at the backend
  boundary: the camera must belong to the tenant that owns the
  presenting API key.
- Cross-branch visibility requires an org-wide role; cross-tenant
  is `super_admin` only and audited.

### Access control for live streams

- Live tile subscriptions are **per camera** and authorised by the
  user's branch scope.
- Snapshot downloads use **short-lived backend-issued signed URLs**;
  MinIO bucket policies forbid public listing.
- Snapshot reads are audited.

### Privacy

- Face recognition is gated by **active customer consent**; an
  embedding is matched only when consent for `FACE_RECOGNITION` is
  granted (BR-22, BR-23).
- Consent withdrawal triggers a deletion of the customer's
  embeddings within the privacy SLA; the AI Engine receives an
  invalidation signal and stops attempting recognition.

---

# Event System Integration

### Events generated by the camera pipeline

| Event | Source layer | Cardinality | Carries |
|-------|--------------|-------------|---------|
| `CameraRegistered` | Backend | 1 / camera lifecycle | camera id, branch, configured pipelines |
| `CameraProbed` | AI Engine | per probe | measured fps, codec, resolution |
| `CameraOnline` | Backend | per state change | camera id, since |
| `CameraDegraded` | Backend | per state change | reason, metrics |
| `CameraOffline` | Backend | per state change | last_seen_at |
| `CameraError` | Backend | per state change | error code, message |
| `CameraReassigned` | Backend | per reassignment | old/new branch |
| `CameraDisabled` / `CameraEnabled` | Backend | per change | actor |
| `FrameCaptured` *(internal, AI Engine)* | AI Engine | per sampled frame | not published to backend (volume); used internally |
| `ObjectDetected` *(internal)* | AI Engine | per detection | bbox, class, confidence; not published as domain event (volume) |
| `MotionDetected` | AI Engine | sparse | zone, magnitude |
| `TrackingSessionStarted` / `TrackingSessionEnded` | AI Engine | per session | track_id, class, customer_id (if any) |
| `CustomerDetected` | AI Engine | rate-limited | customer_id (only with consent), confidence |
| `ProductPickedUp` / `ProductReturned` | AI Engine | per cart action | product_id, customer_id, confidence |
| `ProductRecognized` (auto-cart) | AI Engine | per high-confidence recognition | product_id, cart context |
| `ShelfBecameEmpty` | AI Engine | per detection | product_id, branch_id, confidence |
| `QueueDetected` | AI Engine | rate-limited | zone_id, length, wait_estimate |
| `TheftDetected` | AI Engine | rare | track_id, evidence snapshot id, confidence |
| `SnapshotCaptured` | AI Engine | per snapshot | snapshot_id, purpose, linked event |
| `ModelDeployed` | Backend | per deployment | model_name, version, pipelines |

### Event flow into the backend system

```
[AI Engine — Rule Engine]
        │ produces AIEvent (event_type, payload, confidence,
        │ occurred_at, correlation_id, optional snapshot ref)
        ▼
[AI Engine — Event Publisher]
        │ delivers to backend via authenticated channel
        │ (HTTP ingestion endpoint or message broker)
        ▼
[Backend — AI Event Gateway]
        │ validates: org/branch/camera scope, schema, timestamps,
        │ confidence, snapshot ownership
        │ writes AIEvent (partitioned table)
        │ optionally writes DetectionResult sample
        ▼
[Backend — Application Services / EventBus]
        │ - smart cart: ProductPickedUp → CartService.add_item
        │ - inventory: ShelfBecameEmpty → InventoryService.flag
        │ - notifications: TheftDetected → NotificationService.send
        │ - analytics: increment aggregates
        ▼
[Outputs]
        - DB writes (transactional)
        - Notifications (in-app, email, webhook)
        - WebSocket fan-out to dashboards
        - Audit entries for sensitive actions
```

### Cardinal rules for the event flow

- The AI Engine **proposes**; the backend **decides** (Architecture
  Contract §2.2). AI events never write to business tables
  directly.
- Events are **idempotent on `eventId`** — duplicates from retries are
  safe.
- Events have **schema versions** (`event_type@vN`) so the catalogue
  can evolve.
- The publisher is **bounded**: when the backend is unreachable, the
  engine buffers up to a small cap and drops further events with
  metrics; it does not pile up unbounded memory.

---

# Future Improvements

### Pipeline

- **Cross-camera re-identification** to maintain a single shopper
  identity across cameras in the same branch (privacy-respecting,
  on-device features only).
- **Edge model distillation** so low-power edge devices run the same
  pipelines with a smaller footprint.
- **On-camera AI** (where supported) to offload detection at the
  camera itself.
- **Adaptive sampling** — increase frame rate during events of
  interest (motion in checkout zone), reduce it otherwise.

### Storage

- **WebRTC SFU** for many-viewer live tiles.
- **Tile pyramids** for snapshots so the dashboard fetches the right
  size for the device.
- **Per-tenant retention overrides** with regulatory floor enforced
  by the platform.

### Operations

- **Automatic pipeline tuning** — the engine measures latency,
  drops, and CPU/GPU usage and proposes a target_fps and pipeline
  mix per camera.
- **Camera onboarding wizard** with auto-detection of codec, fps,
  resolution, and zone proposals.
- **Multi-region orchestration** with regional engines and a
  central control plane.

### Privacy and compliance

- **On-device face matching** so face embeddings never leave the
  branch.
- **Differential privacy** for analytics aggregates released to
  third parties.
- **Tamper-evident snapshots** signed at capture time.

### Anti-goals (deliberately not on the plan)

- 24/7 DVR-style recording in VisionMart itself.
- Real-time video shipped through Postgres or the SPA backend.
- Unbounded queues anywhere in the pipeline.
- Single shared GPU node as a single point of failure.
- Business logic implemented inside the AI Engine.

---

*This document is the canonical Camera Management & Video Pipeline
design. Any change to ingestion, AI input, storage, streaming, or event
flow requires a PR that updates **only this file** (and, when needed,
an ADR explaining the rationale).*
