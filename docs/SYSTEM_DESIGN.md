# VisionMart — System Design & Data Architecture

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/SYSTEM_DESIGN.md`
> **Owner:** Lead System Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope of this document:** high-level system design only. No code, no
> SQL, no implementation details. Conceptual diagrams are text-based.
> Where this document conflicts with implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract](ARCHITECTURE_CONTRACT.md) ·
> [Domain Model](DOMAIN_MODEL.md) ·
> [ADRs](adr/README.md) ·
> [Product Backlog](PRODUCT_BACKLOG.md) ·
> [Development Roadmap](05_DEVELOPMENT_ROADMAP.md)

---

# System Overview

VisionMart is a **multi-tenant, multi-branch, AI-augmented retail
operations platform**. The system observes the physical store with
cameras, reasons about what is happening using a vision pipeline, and
combines those signals with traditional POS, catalog, and inventory
workflows to deliver:

- Real-time operational awareness (queues, alerts, theft, low stock).
- AI-assisted checkout (smart carts).
- Customer / staff analytics and reports.
- A unified web management plane for managers, cashiers, and admins.

### Logical components

| Component | Responsibility | Runtime form |
|-----------|----------------|--------------|
| **Cameras** | Source of frames. | Physical IP cameras (RTSP/RTMP/HTTP). |
| **AI Engine** | Frame capture, model inference, tracking, event emission. | Separate Python process; CPU or GPU host. |
| **Backend API** | Business logic, persistence, auth, RBAC, REST + WebSocket. | Python / FastAPI process(es). |
| **Background Worker** | Async jobs (reports, exports, AI batch, notifications). | Celery worker process(es). |
| **Postgres** | System of record for business data. | Single-writer relational store. |
| **Redis** | Cache, queues, pub/sub, rate limit, real-time state. | In-memory KV. |
| **MinIO / S3** | Binary storage (frames, snapshots, exports, embeddings). | Object store. |
| **Nginx** | TLS termination, reverse proxy, security headers, rate limit. | Edge proxy. |
| **Web Dashboard** | Operator/management UI. | React SPA in browser. |

### Two deployment shapes (per ADR-015)

- **Tier 1 — Single-node:** the full stack on one VM behind one Nginx,
  managed by `docker compose`.
- **Tier 2 — Kubernetes:** stateless API + workers + AI engine pods, with
  managed Postgres / Redis / S3.

---

# Architecture Diagram (text-based)

### High-level component diagram

```
                           ┌──────────────────────────────┐
                           │        Web Dashboard         │
                           │     (React + WebSocket)      │
                           └──────────────┬───────────────┘
                                          │ HTTPS / WSS
                                          ▼
                              ┌──────────────────────┐
                              │   Nginx (Edge)       │
                              │ TLS · headers · RL   │
                              └──────────┬───────────┘
                                         │
                                         ▼
                   ┌──────────────────────────────────────┐
                   │           Backend API                │
                   │   FastAPI · REST /api/v1 · /ws/v1    │
                   │      Application + Domain layers     │
                   └──┬──────────────────────────┬────────┘
                      │                          │
       ┌──────────────┘                          └────────────────┐
       │                                                          │
       ▼                                                          ▼
┌────────────┐                                          ┌──────────────────┐
│ PostgreSQL │  <── Alembic migrations ──┐              │ Celery Workers   │
│  (OLTP SoR)│                           │              │  background jobs │
└─────┬──────┘                           │              └─────────┬────────┘
      │ ▲                                │                        │
      │ │ logical repl. (analytics)      │                        │
      ▼ │                                │                        ▼
 ┌────────────┐    ┌──────────────┐      │              ┌──────────────────┐
 │  Read      │    │   Redis      │◄─────┴── pub/sub ──►│   AI Engine      │
 │  replica   │    │ cache · queues│                    │ frames · models  │
 │ (analytics)│    │ pub/sub · RL │      events         │ tracking · evts. │
 └────────────┘    └──────┬───────┘ ◄─────events─────── └─────────┬────────┘
                          │                                       │ RTSP/RTMP/HTTP
                          │                                       ▼
                          │                              ┌──────────────┐
                          │                              │  IP Cameras  │
                          │                              └──────────────┘
                          ▼
                   ┌─────────────┐
                   │ MinIO / S3  │
                   │ frames, etc.│
                   └─────────────┘
```

### Layered view of the backend process

```
                    ┌─────────────────────────────────┐
                    │  Presentation Layer (FastAPI)   │  REST + WebSocket
                    ├─────────────────────────────────┤
                    │  Application Layer (Use Cases)  │  transactions, orchestration
                    ├─────────────────────────────────┤
                    │  Domain Layer (Aggregates)      │  invariants, business rules
                    ├─────────────────────────────────┤
                    │  Infrastructure Layer           │  ORM, Redis, MinIO, EventBus
                    └─────────────────────────────────┘
```

### Canonical end-to-end flow

```
[Camera]
   │  RTSP frame
   ▼
[AI Engine]
   │  detection + track + recognition
   ▼
(EventBus / Redis Streams)
   │
   ▼
[Backend Application Service]
   │  apply business rules, persist
   ▼
[Postgres]  ───────►  emit domain event  ─────►  [Redis Pub/Sub]
                                                       │
                                                       ▼
                                                [WebSocket Fan-out]
                                                       │
                                                       ▼
                                              [Web Dashboard]
```

---

# Data Flow

> Every data flow below either matches the diagrams above or is invalid.

### 1. Video frames flow

```
Camera ──RTSP/RTMP/HTTP──► AI Engine (frame capture stage)
                              │
                              ├── most frames discarded after inference
                              ├── selected frames → MinIO (snapshots, evidence)
                              └── NEVER sent to backend/database/frontend
```

- Raw frames are **owned by the AI Engine** and never traverse the
  backend or browser.
- Only **derived artefacts** (snapshots, short clips for incidents,
  embeddings) reach storage, and only through MinIO via signed URLs
  issued by the backend.

### 2. AI detection results flow

```
AI Engine
   │  per-frame detections, tracks, recognitions
   ▼
Apply per-camera config (pipeline kinds, thresholds)
   │
   ▼
Emit DomainEvents (e.g. ProductPickedUp, QueueDetected)
   │
   ▼
EventBus (in-process now; Redis Streams later — see ADR-014)
   │
   ▼
Backend application services (one per consuming context)
   │
   ├── persist outcomes to Postgres (e.g. cart update)
   ├── emit downstream events
   └── publish to Redis Pub/Sub for UI fan-out
```

### 3. Events flow

```
Producer context ──► EventBus ──► subscribed handlers
                                  │
                                  ├── transactional handler (in-process)
                                  ├── async handler (Celery)
                                  └── UI fan-out (Redis Pub/Sub → WebSocket)
```

- Events are **idempotent on `eventId`**.
- Events are **informational** for the consumer; they may not be relied
  upon for in-process invariants (those live in the producing aggregate's
  transaction).

### 4. User interactions flow

```
Browser
   │  HTTPS request (with JWT) / WSS frame
   ▼
Nginx (TLS, rate-limit, headers)
   │
   ▼
Backend API
   ├── Auth + RBAC + tenant scope check
   ├── Presentation → Application service
   ├── Application → Domain + Repositories
   ├── Repositories → Postgres / Redis / MinIO
   └── Standard response envelope back to browser
```

### 5. Inventory updates flow

```
Trigger source:
   ├── manual stock movement (UI)
   ├── cart/order lifecycle (events from Order & Cart)
   └── AI shelf events (events from AI Processing)

   ▼
Inventory application service
   ├── load InventoryItem aggregate
   ├── enforce non-negative + reservation invariants
   ├── append StockMovement
   └── commit transaction

   ▼
Emit InventoryUpdated / LowStockDetected
   ▼
Notification + Analytics + UI fan-out
```

---

# Real-time System

### What is real-time (≤ 1 s end-to-end target)

- Live camera tiles in the dashboard.
- Detection / tracking events relevant to the operator (queue length,
  shelf empty, theft, low stock).
- AI-driven cart updates (smart cart).
- Notification inbox toasts and unread counts.
- Camera online/offline transitions.

**Transports:** AI Engine → backend via the EventBus; backend → browser
via WebSocket; cross-instance fan-out via Redis Pub/Sub.

### What is async (seconds → minutes)

- Notification delivery via email / webhook (Celery).
- Stock-take posting and bulk catalog imports.
- Image post-processing (thumbnails, embeddings).
- AI human-review queue updates.
- Search index updates.

**Transport:** Celery on Redis broker; some flows also publish events
upstream when complete.

### What is batch (minutes → hours / daily)

- Scheduled reports (daily revenue, weekly inventory).
- Analytics roll-ups into materialised aggregates.
- Backup jobs and lifecycle / cleanup jobs (expired carts, archived
  notifications, stale snapshots).
- Model evaluation runs and per-tenant fine-tuning.

**Transport:** Celery Beat scheduling Celery tasks.

### Real-time delivery contract

- Browser opens **one** authenticated WebSocket per session.
- Subscriptions are **topic-based** and **permission-checked**
  (`org.{id}.camera.{cameraId}`, `branch.{id}.alerts`,
  `notifications.user.{id}`).
- Messages carry a **monotonic offset**; clients backfill missed
  messages on reconnect.
- Real-time payloads are **informational summaries**, not the source of
  truth — for any user action, the browser re-queries the REST API.

---

# Database Design (Conceptual)

### Guiding principles

- **One Postgres** as the system of record (ADR-004).
- One **logical schema** per tenant is **not** used — all tenants share
  the same schema with `organization_id` columns and strict query-level
  scoping.
- **JSONB** for flexible payloads (product attributes, AI configs, audit
  diffs, notification payloads) where rigid columns would be brittle.
- **No business logic in the database** (Architecture Contract §2.6).

### Core conceptual tables (no SQL — names only)

| Domain area | Tables (conceptual) |
|-------------|---------------------|
| Tenancy | Organizations · Branches · OrganizationSettings |
| Identity | Users · Roles · Permissions · UserRoles · RolePermissions · Sessions · ApiKeys |
| Catalog | Categories · Products · ProductMedia |
| Inventory | InventoryItems · StockMovements · Stocktakes |
| Customer | Customers · CustomerConsents · FaceEmbeddingRefs |
| Employee | Employees · EmploymentRecords |
| Camera | Cameras · CameraHealthStates · CameraAIConfigs · Zones |
| Sales | ShoppingCarts · CartLines · Orders · OrderLines · Payments · Refunds |
| AI | VisionPipelines · ModelRegistrations · DetectionEvents (hot) · Snapshots (metadata only) |
| Notification | Notifications · NotificationPreferences · Subscriptions · DeliveryAttempts |
| Analytics | FootfallAggregates · DwellAggregates · ConversionAggregates · QueueAggregates · HeatmapTiles · StaffActivityAggregates |
| Reporting | Reports · ReportRuns · ScheduledReports |
| Audit | AuditLogs |

### High-level relationships (conceptual)

- Every business row links back to **Organization** and (where
  applicable) **Branch**.
- Catalog Product is referenced (by ID) from Inventory, CartLine,
  OrderLine, AI ModelRegistration.
- Branch is referenced from Inventory, Camera, Employee, Order, Cart,
  Notification target.
- Customer is optionally referenced from Cart / Order; consent is
  separate.
- AI events reference Camera (and may reference a Track ID); they
  **never** reference internal infrastructure of other contexts.
- Cross-module SQL relationships (`relationship()` navigation) are
  **forbidden** (Architecture Contract §2.5). FK columns are allowed and
  navigation goes through the owning module's repository.

### Multi-branch & multi-tenant data isolation strategy

1. **Schema-level discriminator** — every tenant-scoped table includes
   `organization_id` (and `branch_id` where applicable).
2. **Repository-level enforcement** — base repositories inject the
   `organization_id` predicate; raw queries are reviewed in CI.
3. **Application-level enforcement** — every request's tenant + branch
   scope is derived from the authenticated principal and threaded
   through application services; it cannot be supplied by the client.
4. **Negative tests** — the test suite includes deliberate
   cross-tenant access attempts that must fail.
5. **Future option** — schema-per-tenant or DB-per-tenant for premium
   customers; the abstraction is in place but not used in v1.

### Indexing strategy (conceptual)

- **Tenancy indexes** — `(organization_id, …)` as the leading column on
  almost every table; `(organization_id, branch_id, …)` for branch-hot
  paths.
- **Lookup indexes** — `(organization_id, slug)` for code/slug lookups
  (categories, products, branches, etc.).
- **Operational indexes**:
  - `Products`: `(organization_id, sku)` unique; trigram on `name` for
    search; `(barcode)` for POS scans.
  - `InventoryItems`: `(product_id, branch_id)` unique; partial index
    on `quantity <= reorder_level` for low-stock queries.
  - `Orders`: `(organization_id, created_at)` for time-window queries;
    `(organization_id, code)` unique.
  - `DetectionEvents`: `(camera_id, occurred_at)`; partitioned by time
    (see retention).
  - `AuditLogs`: `(organization_id, occurred_at)`,
    `(resource_type, resource_id)`.
- **JSONB indexes** — GIN where filters target JSONB attributes (e.g.
  product attributes filter).
- **Don't index everything** — every index has write cost. Indexes are
  driven by measured query patterns, not by anticipation.

### Data retention rules (conceptual)

| Data class | Default retention | Notes |
|------------|-------------------|-------|
| **Orders, Payments, Refunds, AuditLogs** | Indefinite (regulatory) | Tenant may extend, never shorten below local regulation. |
| **InventoryMovements** | Indefinite | Same as above. |
| **Notifications (in-app)** | 90 days | Read state preserved; older archived. |
| **DetectionEvents (hot)** | 30 days | Aggregated into Analytics before purge. |
| **Snapshots / clips** | 30 days | Longer on incident-linked items. |
| **Frames in MinIO** | Hours | Most discarded; only sampled frames retained. |
| **Face embeddings** | Until consent withdrawal | Deleted within privacy SLA on withdrawal. |
| **WebSocket / live state in Redis** | Seconds to minutes | TTL-driven. |
| **Celery task results** | 24 h | Failed-task tracebacks 7 days. |

Time-based partitioning is used for high-volume tables
(`DetectionEvents`, `AuditLogs`, analytics aggregates) so retention is a
fast partition drop rather than a row scan.

---

# AI Pipeline

### Pipeline shape (mandatory per Architecture Contract §2.2)

```
Camera Input
   │  RTSP / RTMP / HTTP, per-camera target FPS
   ▼
Frame Extraction
   │  decode, downsample, frame-rate control
   ▼
Preprocessing
   │  resize, normalise, color-space, ROI crop
   ▼
YOLOv8 Detection
   │  per-frame bboxes + class + confidence
   ▼
ByteTrack Tracking
   │  stable Track IDs across frames
   ▼
Recognition / Specialised heads (per pipeline kind)
   │  product recognition · face match (consented only)
   │  shelf occupancy · queue · heatmap · theft
   ▼
Business Rule Engine (in AI Engine)
   │  apply confidence thresholds (BR-25..28)
   │  debounce / aggregate (e.g. ShelfBecameEmpty after T seconds)
   ▼
Event Generation
   │  ProductPickedUp · ShelfBecameEmpty · QueueDetected · TheftDetected · …
   ▼
Backend Processing
   │  context application services react and persist
```

### Latency considerations

- **Per-frame inference target:** ≤ 100 ms on a single GPU camera, ≤ 500
  ms on CPU-only deployments. Measured per-pipeline and per-camera.
- **End-to-end (capture → event published):** ≤ 1 s SLO.
- **End-to-end (event → user-visible alert):** ≤ 1.5 s SLO inside a
  single deployment.
- Each pipeline stage emits its own latency metric; backlog is bounded
  with explicit drop-or-skip policies (configurable per camera).

### GPU vs CPU split

| Stage | Preferred runtime | Fallback |
|-------|-------------------|----------|
| Frame decode | CPU (with HW accel where available) | CPU |
| Preprocessing | CPU (vectorised) | CPU |
| Detection (YOLOv8) | GPU via TensorRT / CUDA | CPU via ONNX Runtime |
| Tracking (ByteTrack) | CPU | CPU |
| Recognition / Re-ID | GPU | CPU (degraded accuracy ladder) |
| Aggregation / rule engine | CPU | CPU |

- Cameras can be **pinned** to AI Engine nodes; GPU nodes serve the
  cameras that need real-time recognition; CPU nodes serve everything
  else (and act as failover).
- Model registry decides which backend (TensorRT / CUDA / CPU ONNX) is
  active per pipeline (see ADR-008, story `VM-AI-CORE-06`).

### Batch vs real-time inference

- **Real-time** — every camera-attached pipeline: detection, tracking,
  product recognition for smart cart, queue, theft.
- **Batched (mini-batch within a single GPU node)** — multiple cameras
  share a GPU when their FPS budgets allow; the AI Engine batches
  frames across cameras to maximise throughput.
- **Batch (offline)** — analytics roll-ups, model evaluation, retraining
  jobs, embedding re-indexing. Run on dedicated GPU nodes or in cloud
  batch queues, never on the real-time inference path.

### Model update strategy

- Models are stored in MinIO / model registry with hash + metadata.
- Per-tenant **active version** is a configuration value; updating it
  triggers a hot-swap that drains in-flight inferences gracefully (no
  dropped streams).
- Rollback is symmetric — switch the active version back; previous
  weights remain in the registry.
- A/B comparison: two versions can run shadow-mode on a sampled subset
  of frames; results are compared in metrics, not in production
  decisions.
- All version changes emit `ModelDeployed` and are auditable.

---

# Event System

### Producers

- **AI Processing** — vision events (Customer/Product Detected, Picked
  Up, Theft, Queue, Heatmap, Shelf state).
- **Order & Cart** — cart and order lifecycle, payments.
- **Inventory** — stock changes, low stock.
- **Camera** — camera registration, online/offline.
- **Identity & Access** — auth events.
- **Customer / Employee / Organization** — lifecycle events.

### Consumers

- **In-process synchronous-but-decoupled handlers** for cross-context
  side effects (e.g. `OrderPaid` → inventory commit + receipt
  notification).
- **Celery workers** for slow side effects (email, webhook, report
  generation).
- **WebSocket fan-out** for UI updates.
- **Audit** for security/compliance events.
- **Analytics** for aggregation.

### Event flow

```
Producer aggregate
   │  state change committed
   ▼
EventBus.publish(domainEvent)
   │
   ├── in-process subscribers (best-effort, isolated failures)
   ├── Celery-bound subscribers (`apply_async` to async queue)
   └── Redis Pub/Sub topic for cross-instance fan-out
                       │
                       ▼
              WebSocket gateway(s) on every backend instance
                       │
                       ▼
                 Subscribed browsers
```

### Event persistence strategy

- **Domain events that drive correctness** (rare) are persisted in the
  same transaction as the aggregate change (transactional outbox
  pattern) and dispatched after commit.
- **Informational events** (the majority) are dispatched best-effort and
  may be lost on a crash; consumers tolerate loss.
- **High-volume AI detection events** are persisted **selectively** —
  raw per-frame detections are aggregated and only meaningful
  derivatives (`ProductPickedUp`, `ShelfBecameEmpty`, etc.) are stored.
- **Audit-grade events** are written to the Audit context's
  append-only log unconditionally.
- **Replay** — when the broker layer evolves (ADR-014), persisted
  events can be replayed into new consumers (e.g. a new analytics
  module).

### Naming and versioning

- `<Subject><Verb-Past-Tense>` — `OrderPaid`, `ShelfBecameEmpty`.
- Each event has `eventVersion`; producers may publish multiple
  versions in parallel during migration windows; unknown versions are
  ignored by consumers (see Domain Model §Event versioning).

---

# Cache Strategy

> Redis is governed by ADR-010 and Architecture Contract §2.6. Redis
> **MUST NOT** hold a single source of truth for business data.

| Use case | Key namespace | TTL | Notes |
|----------|---------------|-----|-------|
| **Real-time cart state** | `cart:{branchId}:{cartId}` | minutes (cart TTL) | Mirror of the authoritative cart; absorbs AI bursts; reconciled to Postgres on every commit. |
| **Active sessions / token revocation** | `auth:session:{sessionId}` · `auth:revoked:{tokenId}` | until expiry | Revocation list is the only authoritative thing here; sessions themselves are also persisted. |
| **Camera stream buffer** | `cam:frame:{cameraId}:{seq}` | seconds | Short ring buffer to absorb decoder hiccups; never durable. |
| **Temporary AI results** | `ai:track:{cameraId}:{trackId}` | seconds | Aggregations across a sliding time window before the rule engine emits a stable event. |
| **Hot data caching** | `cache:product:{id}` · `cache:category:tree:{orgId}` | minutes (with explicit invalidation) | Read-through caches for catalog and config lookups. |
| **Rate limits** | `ratelimit:{route}:{principal}` | window-aligned | Counter per token per window. |
| **Pub/Sub fan-out** | `pubsub:org.{id}.*` | n/a | Cross-instance WebSocket distribution. |
| **Idempotency keys** | `idem:{route}:{key}` | 24 h | Stores the prior response to replay on retry. |
| **Celery broker + result backend** | `celery:*` | per task config | Job queues and short-lived results. |

### Invalidation discipline

- Every cached entry has an **explicit TTL** or an **explicit
  invalidation path**.
- Write paths invalidate (or refresh) cache entries before returning
  success.
- A cache miss must always be safe — it falls through to Postgres.
- A Redis outage degrades performance but **never** loses business
  data.

---

# Scalability Plan

### Multi-camera scaling

- Cameras are partitioned across AI Engine workers by a hash of
  `(organizationId, cameraId)`; each worker owns a disjoint set.
- Adding a worker re-balances ownership via consistent hashing; no
  central scheduler.
- A worker's per-camera load is bounded by FPS budget × pipeline cost;
  beyond the budget, frames are dropped (configurable policy) rather
  than queued unbounded.

### Multi-branch scaling

- Multi-branch is a **modelling** concern, not a scaling concern — all
  branches share the same backend and database.
- Hot-path queries always include `organization_id` and `branch_id`
  predicates, so adding branches scales linearly with index usage.
- A noisy branch (high event volume) does not impact another branch
  beyond shared resource limits, which are bounded by per-tenant rate
  limits.

### AI GPU scaling

- AI Engine pods are placed on **GPU node pools**.
- Autoscaling is **queue-depth-based** (KEDA or equivalent), not just
  CPU/GPU utilisation.
- GPU memory budgets are tracked per pipeline; the engine refuses to
  load models that would exceed the budget on a node.
- Cold-start of a new GPU pod is masked by the always-on warm pool
  policy (`minReplicas ≥ N` per tenant tier).

### Backend horizontal scaling

- All API instances are **stateless** (Architecture Contract §1).
- Sticky sessions are **not** required for correctness; they may be
  used as an optimisation for WebSocket affinity.
- Background workers (Celery) scale independently on queue depth.
- WebSocket gateway can be co-resident with the API process today and
  extracted into its own pool when connection counts justify it.

### Database scaling strategy

- **Primary scaling lever** — query and index quality. Most performance
  cliffs are query-level, not database-level.
- **Connection pooling** with PgBouncer in front of Postgres to absorb
  bursty API traffic.
- **Read replicas** for analytics and reporting; the application
  marks read-only paths and routes them through a read-only session.
- **Partitioning** for high-volume tables (`DetectionEvents`,
  `AuditLogs`, analytics aggregates) by time, enabling fast retention.
- **Vertical scaling** of the primary up to a documented limit; beyond
  that, multi-tenant sharding is the next option.
- **Per-tenant sharding** is on the menu but not adopted; the
  multi-tenant predicate model is designed to make it possible later
  without rewriting domain code.

---

# Failure Handling

### Camera disconnect handling

- Stream client reconnects with **exponential backoff + jitter** up to
  a max interval.
- After N consecutive failed reconnects, the camera transitions to
  `OFFLINE` and emits `CameraWentOffline`.
- Offline cameras are excluded from pipeline budgets; recovery
  re-includes them automatically.
- The dashboard reflects the offline state within the configured SLO.

### AI service failure fallback

- Each AI Engine worker has a **liveness** and **readiness** signal; an
  unhealthy worker is removed from the camera-ownership ring.
- A pipeline that fails to load a model falls back to the previous
  registered version and raises an alert; if no version is loadable,
  the pipeline is disabled for the affected cameras and an incident is
  opened.
- Inference errors per frame are logged with metrics; the pipeline
  does not retry the same frame — it processes the next one.
- **AI down ≠ retail down.** The backend continues to serve POS, cart,
  and order flows in manual mode. AI-only features (smart cart, queue
  alerts) are silently degraded with a banner in the UI.

### Event loss recovery

- Events that drive **correctness** use the transactional outbox
  pattern: persisted atomically with the aggregate change and
  dispatched after commit. Lost dispatches are retried from the
  outbox.
- Events that are **informational** (most AI events) may be lost on
  crash. The system tolerates this; the source of truth is the
  aggregated state in Postgres.
- WebSocket clients keep a **monotonic offset**; on reconnect they
  request a backfill of messages since the last seen offset (bounded
  to a short window — older gaps require a UI refresh).

### Database retry strategy

- Transient errors (deadlocks, serialisation failures) are retried with
  exponential backoff up to a small N (typically 3) **inside the
  application layer**, not inside the domain.
- Idempotency keys (on mutating endpoints) make retries safe end-to-
  end (`VM-API-06`).
- A persistent database outage triggers:
  - Healthcheck `/ready` returns 503; load balancer removes the
    instance from rotation.
  - WebSocket gateway holds connections but pauses publishes.
  - Operators are paged.

### Other failure modes (summary)

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Redis outage | health probe + circuit breaker | API runs in degraded mode (no cache, no pub/sub, no rate limit data plane); writes still succeed; UI still receives REST responses. |
| MinIO outage | upload health probe | New uploads queue and retry; presigned reads fail gracefully with placeholders. |
| Celery broker outage | worker reconnect logic | Tasks queue locally up to a bound; user-visible jobs surface as "pending". |
| Payment gateway outage | ACL inside Order & Cart | Card/QR payments disabled; cash + later-reconciliation path remains open. |

---

# Security Design

### Authentication flow (JWT)

```
[Login request: email + password]
   ▼
[Backend]
   ├── Rate-limit + lockout check
   ├── Verify password hash
   ├── Issue access token (short TTL) + refresh token (longer TTL)
   ├── Emit UserLoggedIn / UserLoginFailed
   ▼
[Client stores tokens in the most restrictive storage available]
   │
   ▼
[Subsequent request: Authorization: Bearer <access>]
   ▼
[Backend]
   ├── Verify signature + expiry
   ├── Load principal (user, org, branch scope, roles, permissions)
   ├── Enforce RBAC at the endpoint
   └── Inject scope into application service
```

- Refresh tokens **rotate** on every use; reuse of a rotated token
  invalidates the lineage and forces re-login.
- Logout revokes refresh tokens; revocation list lives in Redis with
  TTL = remaining lifetime.

### Role-Based Access Control (RBAC)

- Every protected endpoint declares a **required permission** (e.g.
  `inventory.adjust`).
- A role is a bundle of permissions; users hold one or more roles.
- The system ships with seed roles (`super_admin`, `org_admin`,
  `branch_manager`, `cashier`, `viewer`); custom roles are allowed
  within a tenant.
- Authorization decisions are made in **one** layer (the policy
  enforcement point), never sprinkled across handlers.

### Multi-branch isolation security

- Every request's principal includes its `organizationId` and the set
  of allowed `branchId`s.
- Repositories transparently inject these scopes into every query that
  reads tenant-scoped data.
- Direct API requests for cross-branch data with insufficient scope
  return 403 (audited).
- Background jobs run in the **principal-less system role** with
  explicit tenant context derived from the job payload; they cannot
  silently cross tenants.

### API security layer

- TLS everywhere (TLS 1.2 minimum, TLS 1.3 preferred).
- Strict security headers (HSTS, CSP, Referrer-Policy,
  X-Content-Type-Options, X-Frame-Options) at Nginx.
- Per-route rate limits at Nginx; stricter limits on auth endpoints.
- **Input validation at the edge** (Pydantic schemas in the API layer,
  WebSocket payload schemas at the gateway).
- **Output encoding** to defeat XSS in any HTML surface (the SPA is
  React, which encodes by default; webhook payloads are JSON only).
- Consistent error envelope — no stack traces leak in production.
- Idempotency keys to defeat duplicate-submission classes of attacks.

### Data protection rules

- Passwords stored as **modern hashed** values (Argon2 / bcrypt-class)
  with per-user salt; never plaintext.
- JWT signing keys sourced from the secret manager; rotated on a
  schedule.
- PII fields encrypted at rest (database-level or column-level
  depending on environment).
- Face embeddings stored only with **active consent**
  (`CustomerConsent` for `FACE_RECOGNITION`); deleted within the
  privacy SLA on consent withdrawal.
- Frames and snapshots in MinIO use bucket policies; access is via
  signed URLs only; no public buckets.
- Audit log records every privileged action and every consent change.
- Dependency scanning + image-vulnerability scanning gate every merge
  and every release.

---

# Future Improvements

> Tracked here for visibility; promoted into the roadmap or an ADR when
> a real trigger emerges.

### Vision & AI

- **Cross-camera re-identification** as a first-class context (today
  it is a per-pipeline feature inside AI Processing).
- **Active-learning loop** — turn the human-review queue into
  automated retraining batches with quality gates.
- **Edge inference at the camera** — push lightweight models onto
  smart NVRs / cameras to reduce backhaul bandwidth.
- **Federated tenant models** — train shared improvements across
  consented tenants without sharing data.

### Platform

- **Transactional outbox + real broker** (Redis Streams, NATS
  JetStream, or Kafka) — promoted from in-process EventBus when a
  context is extracted into its own service (ADR-014).
- **Schema-per-tenant / DB-per-tenant** for premium-tier customers.
- **Multi-region active-active reads** with active-passive writes
  (v2.0 territory).
- **Service extraction** of the AI Engine's control plane and the
  WebSocket gateway when they outgrow co-residency.
- **GraphQL** surface as an *additional* API style for clients that
  need field-level cherry-picking (REST remains primary).

### Operations & Observability

- **Distributed tracing** end-to-end (OpenTelemetry) — correlation IDs
  across browser, backend, AI engine, and brokers.
- **SLO-driven alerting** (error budget burn-rate) instead of static
  thresholds.
- **Chaos engineering** as a recurring practice in staging.

### Business

- **Loyalty & promotions** context with rule engine.
- **Workforce / task management** context.
- **Billing & subscription** context for SaaS.
- **Mobile clerk app** + **mobile manager app** + **customer companion
  app** (roadmap `MOB` epic).

### Anti-goals (explicitly not on the roadmap)

- Acting as a full ERP or WMS.
- Replacing the customer's payroll / HR system.
- A native eCommerce storefront.
- Hosting third-party untrusted AI models without isolation.

---

*This document is the canonical system design. Any change to data flow,
pipeline shape, scaling strategy, or security architecture requires a PR
that updates **only this file** (and, when needed, a new ADR explaining
the rationale).*
