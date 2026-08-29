# VisionMart — Real-time Dashboard, Analytics & Heatmap System

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/37_DASHBOARD.md`
> **Owner:** Lead Data & BI Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** Business-Intelligence-layer **design** only. No code, no
> APIs, no DDL, no framework-specific instructions. Where this document
> conflicts with implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract](ARCHITECTURE_CONTRACT.md) ·
> [Domain Model — Analytics](DOMAIN_MODEL.md) ·
> [System Design](SYSTEM_DESIGN.md) ·
> [Database Design — Analytics aggregates](10_DATABASE_DESIGN.md) ·
> [AI Overview](20_AI_OVERVIEW.md) ·
> [Camera Manager](21_CAMERA_MANAGER.md) ·
> [Cart Engine](26_CART_ENGINE.md) ·
> [WebSocket](16_WEBSOCKET.md)

---

# Dashboard Architecture

The dashboard is the **operational cockpit** of a VisionMart store
network. It does two jobs:

1. **Real-time monitoring** — what's happening *now* in a branch
   (live tiles, alerts, active carts, queues, camera health).
2. **Operational analytics** — what *just happened* and what is
   *trending* (hourly footfall, conversion, heatmaps, theft
   incidents, staff productivity).

The dashboard does **not** generate facts; it **renders** facts the
rest of the platform has already produced and persisted.

### Canonical end-to-end flow

```
[Camera]
   │ frames
   ▼
[AI Engine]
   │ AIEvent + DetectionResult sample
   ▼
[Backend — AI Event Gateway / Application Services]
   │ writes to Postgres (event + aggregates)
   │ updates Redis hot mirrors (counters, gauges)
   │ publishes Domain Events on the EventBus
   ▼
[WebSocket Gateway]                     [Background — Celery roll-up]
   │ fan-out per topic                  │ rolls events into Analytics aggregates
   ▼                                    ▼
[Dashboard UI]                          [Postgres — partitioned aggregates]
                                         │
                                         ▼
                                  [Dashboard UI on demand REST]
```

### Data sources the dashboard relies on

| Source | Purpose | Typical latency |
|--------|---------|------------------|
| **WebSocket pub/sub (backend → SPA)** | Live tiles, counters, AI events, camera status | ≤ 1 s |
| **Redis hot counters / gauges** | "Active customers", "products picked per minute", "open carts" | ≤ 1 s |
| **Postgres OLTP (read replica)** | Last-N events, recent orders, current inventory, employee on-shift | seconds |
| **Postgres analytics aggregates** | Hourly / daily / weekly roll-ups, conversion, heatmaps | minutes |
| **MinIO (signed URLs)** | Snapshots / clips attached to alerts | seconds (on-demand) |

### Component responsibilities

| Component | Owns | Does NOT own |
|-----------|------|--------------|
| **Dashboard UI (React SPA)** | Rendering, charts, alert acknowledgement UX, drill-down navigation. | Computing aggregates; storing facts. |
| **Backend metrics service** | KPI calculation, aggregate reads, REST/WebSocket exposure. | AI decisions; cart/order mutations. |
| **AI Engine** | Producing the per-frame and per-event signals the analytics layer aggregates. | Aggregating, persisting, or visualising. |
| **EventBus consumers** | Updating Redis counters and triggering Celery roll-ups. | Holding authoritative business state. |
| **WebSocket Gateway** | Fan-out, per-topic authz, reconnect/backfill. | Computing metrics; storing facts. |

### Design pillars

| # | Pillar | Translation |
|---|--------|-------------|
| 1 | **Read-mostly** | The dashboard never mutates business state; it only acknowledges alerts (which is itself an audited domain action). |
| 2 | **Pre-aggregated, not on-the-fly** | Aggregates are computed continuously by background workers and stored as partitioned tables; the dashboard reads pre-computed rows. |
| 3 | **Authoritative store + hot mirror** | Postgres is authoritative; Redis carries small, bounded hot counters and gauges. |
| 4 | **Idempotent, ordered, backfillable streams** | Every WebSocket subscription supports reconnect-with-offset; no lost or doubled events. |
| 5 | **Permission-checked at every layer** | Tenant + branch scope enforced at the WebSocket subscribe and at every REST query. |
| 6 | **Cheap to widen** | Adding a new aggregate or a new dashboard tile follows a fixed template (event → consumer → aggregate table → tile). |

---

# Analytics Pipeline

### Event ingestion for analytics

Two ingress paths exist; both feed the same downstream stream:

- **AI events** — `AIEvent` rows written by the AI Event Gateway
  (Camera Manager §Event System Integration).
- **Domain events** — emitted by backend application services on the
  EventBus (`CartCreated`, `OrderCreated`, `StockMovementRecorded`,
  `CameraOnline`, `EmployeeClockedIn`, ...).

Each event carries the canonical envelope:

- `event_id` (idempotency key),
- `event_type@vN` (versioned),
- `occurred_at` (UTC, source-of-truth timestamp),
- `produced_at`,
- `organization_id`, `branch_id`, optional `zone_id`,
- a typed payload,
- `correlation_id`.

### Stream processing vs batch processing

| Need | Mode | Mechanism |
|------|------|-----------|
| Live tile updates (≤ 1 s) | **Stream** | Redis counters incremented inside the event handler; WebSocket fan-out. |
| Per-minute / per-hour aggregates | **Micro-batch** | Celery Beat workers tick at a bounded cadence (e.g. every 30–60 s) and roll events into aggregate tables. |
| Daily / weekly roll-ups | **Batch** | Celery Beat jobs at a fixed schedule (e.g. 03:00 local time per branch). |
| Historical re-aggregation (model change, late events) | **Batch backfill** | Idempotent on `(scope, bucket_start, granularity)`; safe to rerun. |

### Aggregation strategy

- All aggregates are **time-bucketed** with a fixed `granularity`
  (`minute`, `hour`, `day`, `week`).
- The primary key of every aggregate is `(scope, bucket_start,
  granularity)` so re-running a job is **safe** (BR-19): the writer
  upserts the row.
- An aggregate row never carries identifiers of *individual* shoppers
  or employees beyond what privacy policy allows; identifiers stay
  inside the *operational* tables (`AIEvent`, `Order`, etc.).

### Time windows

| Window | Use |
|--------|-----|
| **Last 60 s rolling** | Live counters (active carts, picks/min). |
| **Current minute / hour partial** | Live tiles that include the in-progress bucket. |
| **Closed minute / hour buckets** | Charts, exports, daily summaries. |
| **Last 24 h / 7 d / 30 d** | Standard dashboard ranges. |
| **Custom range** | Reports module (separate REST surface). |

> A *closed* bucket is **immutable**. Late-arriving events fall into
> a "late bucket" table for monitoring; the closed aggregate is only
> rewritten by an explicit, audited backfill job.

---

# Heatmap System

### Inputs

- `TrackingSession` paths and per-frame `DetectionResult` samples
  produced by the AI Engine (sampled, not every frame).
- Camera **calibration** (intrinsic + extrinsic) that maps pixel
  coordinates to **store-floor coordinates**.
- The branch's **floor-plan tiling** — a fixed grid of tiles per
  branch (e.g. 50 cm × 50 cm) with stable tile ids.

### Pipeline

```
[AI Engine]
   │ sampled detections (camera-local pixel coords)
   ▼
[Backend — Coordinate Mapper]
   │ pixel → floor-coord (per camera calibration)
   │ floor-coord → tile_id (per branch tiling)
   ▼
[Redis hot heatmap]
   │ HINCRBY tile counter per minute window
   ▼
[Celery roll-up (per minute / per hour)]
   │ flush to HeatmapTile aggregate (Postgres, partitioned)
   ▼
[Dashboard UI]
   │ render tile values as a coloured overlay on the floor plan
```

### Density calculation logic (conceptual)

- A tile's **heat value** for a window is the count (or weighted
  count) of distinct shoppers that occupied it during the window.
- "Distinct" is approximated by unique `(camera_id, track_id)` per
  bucket; this avoids inflating heat from a single person standing
  still.
- For **dwell-heat** maps, weight a tile contribution by the seconds
  the shopper spent in that tile.
- For **interaction-heat** maps, weight tiles where
  `ProductPickedUp`, `ProductReturned`, or `ShelfBecameEmpty`
  occurred.

### Spatial mapping

- Each branch has one or more **floor plans** with a metric scale.
- Each camera has a calibration profile that produces a homography
  to the floor plane (planar approximation per camera FOV).
- Tiles are **stable** for the life of a floor plan; floor-plan
  changes create a new floor-plan version and the heatmap is
  segmented by version.

### Update cadence

- **Per-minute** flush from Redis to a `HeatmapTile` aggregate row
  per `(branch_id, floor_plan_id, tile_id, bucket_start, granularity)`.
- Hourly and daily granularities are rolled up by separate jobs.
- Live heatmap on the dashboard reads the **current partial minute**
  every few seconds via WebSocket; closed buckets come from the
  aggregate table.

---

# Queue Detection

### Identification

- A **queue zone** is a `Zone` of type `checkout` (or `queue`),
  defined per branch and visible from one or more cameras.
- The AI rule engine emits `QueueDetected` for that zone when:
  - `n_people ≥ k` (defaults: 3 people), **and**
  - The condition persists for `t_queue` (default ~30 s), **and**
  - The track movement is *near-stationary* (low average velocity).

### Wait-time estimation

- The platform measures **wait** as the per-shopper time between
  entering the queue zone and reaching the *service line* (a smaller
  sub-zone near the counter). Per-shopper times feed
  `QueueAggregate`.
- Live displayed wait is the **trimmed mean** of recent shoppers
  (e.g. last 5 minutes), not a single-sample reading, so a single
  outlier doesn't whipsaw the gauge.

### Congestion detection

- A queue is **congested** when:
  - `queue_length` rises above the branch's configured *amber*
    threshold for `t_amber`, **or**
  - `wait_estimate` rises above the *amber* wait threshold for
    `t_amber`.
- Escalates to **red** when length or wait exceeds the *red*
  threshold for `t_red`.

### Alerts

- `QueueAmber` and `QueueRed` raise notifications to branch
  managers + cashier supervisors via the Notification Center.
- Alerts are **rate-limited** (one per zone per cooldown window) so
  a sustained busy period does not generate alert storms.
- Auto-resolves with `QueueRecovered` once the condition falls below
  the thresholds for the documented hysteresis window.

---

# Theft Detection Analytics

### Suspicious-behaviour indicators

Each indicator is a **signal**, not a verdict:

- **`TheftSuspected`** — a shopper exits with a `ShoppingCart` that
  has unconfirmed AI pick-ups (no checkout association).
- **Concealment cue** — AI detects an item moving into a bag /
  pocket region.
- **Evasion cue** — a shopper repeatedly avoids a checkout zone
  before exiting.
- **Sensor-bypass cue** — exit-alarm pad triggered without a
  matching order in the cooldown window.
- **Operator flag** — a staff member flags a session for review.

### Risk scoring model (conceptual)

- A composite **risk score** per session is computed from weighted
  signals:
  - `score = w1 · suspected + w2 · concealment + w3 · evasion +
            w4 · bypass + w5 · operator_flag`
- Weights are platform defaults and per-branch tunable within
  documented bounds; weights live in `CameraAIConfig` / branch
  settings.
- Scores bucket into:
  - `low` (visible to ops only, no alert),
  - `medium` (operator review queue, snapshot kept),
  - `high` (live alert + snapshot + clip retained per audit policy).

### Event escalation rules

```
TheftSuspected ─┐
Concealment cue ─┤
Evasion cue ─────┼─► Risk Score Engine ──► [low / medium / high]
Bypass cue ──────┤                          │
Operator flag ───┘                          │
                          ┌─────────────────┴─────────────────┐
                          ▼                                   ▼
            [Medium: review queue]               [High: TheftDetected event]
                          │                                   │
                          ▼                                   ▼
                Branch supervisor UI                  Notification + audit + clip
```

- **No** automatic enforcement action (door lock, blocklist) in v1.
  The platform raises an alert; humans decide.
- Every `TheftDetected` writes an `AuditLog` row inside the same
  transaction as the alert.

### Loss-prevention insights

- Per-branch incidents per period, top product categories involved,
  time-of-day patterns, repeat-offender flag (when supported by
  consented recognition only).
- All loss-prevention analytics are **branch-scoped** in v1; cross-
  branch sharing requires explicit operator policy.

---

# Customer Analytics

### Customer journey (conceptual)

A *journey* is the chronological sequence of events tied to one
`TrackingSession` (and, when consented, the `customer_id`):

1. **Entered** — track first appears in an `entry` zone.
2. **Browsed** — sequence of `(zone_id, dwell_seconds)` pairs.
3. **Interacted** — `ProductPickedUp` / `ProductReturned` events.
4. **Queued** — entered a `checkout` zone.
5. **Converted** — `OrderCreated` associated with the session, **or**
6. **Exited** — `exit` zone without an order.

Journeys for anonymous tracks contribute to *anonymous* aggregates.
Journeys for consented customers contribute to those plus the
customer's own (privacy-respecting) timeline.

### Dwell analytics

- Per `(zone_id, granularity, bucket_start)` aggregates:
  - `unique_visitors`, `avg_dwell_seconds`, `p50/p95_dwell_seconds`,
    `interactions`.
- Aggregates are computed from sampled detections, not from raw
  every-frame data.

### Product interaction tracking

- Each pick-up / return / swap event contributes to a per-product,
  per-branch, per-bucket aggregate.
- The dashboard reports **"interaction-to-purchase" ratio** per
  product: how often a pick-up resulted in a paid order in the same
  session.

### Conversion funnel

```
Visitors (footfall in entry zone)
   │
   ▼
Engagers (touched ≥ 1 product)
   │
   ▼
Carters (≥ 1 cart line, AI or POS)
   │
   ▼
Buyers (OrderCreated)
   │
   ▼
Revenue (OrderTotal)
```

Each step is a stored aggregate; ratios are computed at read time so
the same underlying numbers can be sliced per branch / category /
time range without re-aggregating.

---

# Staff Analytics

### Activity tracking

- Sources:
  - `EmployeeClockedIn` / `EmployeeClockedOut` (Employee context).
  - `OrderCreated` (cashier id).
  - `StockMovement` (`actor_user_id`).
  - Operator actions in the dashboard / cart UI.
  - AI events tagged with `employee_id` when an employee is the
    actor in the frame (e.g. cashier closing a queue ticket).

### Zone coverage

- A `StaffActivityAggregate` rolls up time-in-zone per employee per
  bucket (where the employee was detected inside their assigned
  zone).
- Used to identify **uncovered zones** during peak windows.

### Efficiency metrics (canonical)

- **Items per cashier per hour** (POS or AI-confirmed).
- **Average checkout time** per cashier (cart open → order paid).
- **Stocktake accuracy** per stocktake actor.
- **Restock latency** — time from `ShelfBecameEmpty` to
  `ShelfRestocked`.
- **Queue response time** — time from `QueueAmber` to additional
  cashier joining the line.

### Operational insights

- Manager dashboards highlight **outliers** (top/bottom decile) with
  drill-down to a specific shift.
- All staff metrics are **bounded by privacy policy**: no
  surveillance-style live "where is employee X right now" view;
  aggregates only, with manager-visible drill-downs.

---

# Metrics Engine

### Layout

```
[Domain events / AI events]
   │
   ▼
[Metrics Service]
   ├── Real-time path:
   │     - increments Redis counters / sets gauges
   │     - publishes UI deltas via WebSocket
   │
   ├── Micro-batch path:
   │     - Celery Beat jobs roll into Analytics aggregates
   │
   └── Read path:
         - REST: per-branch KPI snapshot (mix of Redis + Postgres)
         - WebSocket: subscriber-specific deltas
```

### KPI catalogue (canonical, v1)

| KPI | Source | Window | Storage |
|-----|--------|--------|---------|
| Active customers (live) | AI tracks currently in store | rolling | Redis |
| Active carts | Open cart count per branch | live | Redis |
| Items picked / min | `ProductPickedUp` count | rolling 60 s | Redis |
| Orders / hour | `OrderCreated` count | current hour partial | Redis + Postgres |
| Revenue / hour | `OrderTotal` sum | current hour partial | Redis + Postgres |
| Conversion rate | Buyers / Visitors | current hour | Postgres |
| Avg basket size | OrderTotal mean | current hour | Postgres |
| Queue length / wait | Per-zone | live | Redis + Postgres |
| Camera health | Online / degraded / offline counts | live | Redis |
| AI pipeline latency p95 | Per-camera | live | Prometheus + Redis |
| Low-stock items | Count `quantity ≤ reorder_level` | live | Postgres |
| Open theft alerts | `TheftDetected` not acknowledged | live | Postgres |
| Staff on-shift | EmploymentRecord + clock events | live | Postgres |

### Real-time counters

- **Increment-by-1** counters are stored as Redis integers with a
  per-bucket key (e.g. `picks:branch:{id}:min:{minuteEpoch}`).
- **Gauges** (active customers, queue length) are stored as Redis
  hashes with a `version` to detect stale reads.
- All keys have **TTLs** matching the metric's hot window; the
  authoritative roll-up lives in Postgres aggregates.

### Data-freshness strategy

- Live KPIs show their **last-updated** timestamp in the UI; if no
  update arrives within the freshness budget, the tile is
  *de-emphasised* and a `stale` badge appears.
- Aggregates carry their bucket boundaries; the dashboard never
  silently mixes a partial bucket with closed buckets.

---

# Data Storage Strategy

### Tiering (analytics view)

| Tier | Where | Used by | Lifetime |
|------|-------|---------|----------|
| **Real-time hot** | Redis | Live counters, current-window gauges, WebSocket fan-out | seconds to minutes |
| **OLTP warm** | Postgres primary | Recent operational reads (last orders, current inventory) | continuous |
| **Read-replica warm** | Postgres read replica | Heavy analytics queries that read aggregates | continuous |
| **Aggregates (partitioned)** | Postgres (monthly partitions) | Dashboard charts, reports | 12 months hot |
| **Cold archive** | S3 / MinIO Parquet | Long-range BI / data export | per regulation |

### Time-series approach

- Every aggregate table is **monthly range-partitioned** on
  `bucket_start` ([Database Design — Performance Strategy](10_DATABASE_DESIGN.md#performance-strategy)).
- Retention is a **partition drop**, not a row delete.
- Closed partitions are eligible for **detach + Parquet export** to
  cold storage.

### Re-aggregation strategy

- Roll-up jobs are **idempotent** on `(scope, bucket_start,
  granularity)`.
- Backfill jobs can be triggered against any historical range; they
  do not interfere with live ingestion because they target
  different partitions and use upserts.

---

# Visualization Layer

### Dashboard UI data structure

- The SPA holds a **per-page view-model** populated by:
  - One REST call for the **initial snapshot** of the page's tiles
    and aggregates.
  - A small set of **WebSocket subscriptions** for live deltas.
- All view-models are **derived state**; the SPA never persists facts
  beyond the current session.

### Standard chart types

| Tile | Best for | Source |
|------|----------|--------|
| **Real-time counter** | "Active customers", "open carts", "picks / min" | Redis + WebSocket |
| **Line chart** | Footfall / sales over the day | Aggregates |
| **Bar chart** | Top categories, top SKUs | Aggregates |
| **Stacked bar** | Sales by category over hours | Aggregates |
| **Funnel** | Visitors → engagers → carters → buyers | Aggregates |
| **Heatmap (floor plan overlay)** | Foot traffic, dwell, interactions | HeatmapTile aggregate + live partial minute |
| **Camera tile grid** | Live tiles + status badges | WebRTC + WebSocket |
| **Queue strip** | Live queue length per zone | Redis + WebSocket |
| **Alerts panel** | Active alerts (queue, theft, camera, low-stock) | Notification stream |
| **Drill-down table** | Orders / events list with filters | REST + pagination |

### Update frequency strategy

| Tile class | Update rate | Mechanism |
|-----------|-------------|-----------|
| Live counters / gauges | ≤ 1 s | WebSocket |
| Live alerts | ≤ 1 s | WebSocket |
| Current-bucket charts | every 30–60 s | WebSocket "bucket-tick" |
| Closed-bucket charts | on user nav / poll on long stays | REST |
| Heatmap live | every few seconds (partial minute) | WebSocket |
| Heatmap historical | on user nav | REST |

### Permissions and personalisation

- Tiles are **gated by permission** at compose time; a user without
  `audit.view` will not see the audit-related tiles.
- Tiles default to the user's **assigned branch**; users with
  org-wide scope can switch branches via a branch picker.
- Personalisation (which tiles, in which order) is persisted per
  user.

---

# Event Aggregation

### From raw events to insights

```
[Raw event]                   [Aggregator]                       [Aggregate row]
  AIEvent      ─────────►     compute bucket_start (truncate     ┌───────────────────┐
  DomainEvent                  occurred_at to granularity)       │ scope, bucket_start
                               apply privacy / dedupe filter      │ granularity, metrics
                               upsert aggregate row               └───────────────────┘
```

### Normalisation

- All timestamps are **UTC** with a per-row `timezone` reference so
  the dashboard can present in **branch local time**.
- All currencies are normalised to the **branch's currency**; no
  in-flight FX conversion in v1.
- All identifiers carry context: `branch_id`, `zone_id`, `camera_id`
  where applicable.

### Deduplication

- Aggregators dedupe events by `event_id` per
  `(aggregate_table, bucket_start)` to prevent double-counting from
  retries.
- For **distinct-count** metrics (unique visitors), the aggregator
  uses an **approximate set** (e.g. HyperLogLog) per bucket so the
  storage cost is bounded.

### Late events

- Events whose `occurred_at` lies in a **closed** bucket are written
  to a *late-events* spillover table per metric.
- A **late-events monitor** alerts if late traffic exceeds a
  configured floor (typical 0.1 %) — this signals an upstream
  ordering problem.
- Late events do **not** silently rewrite closed aggregates; an
  operator can trigger a documented backfill if material.

### Aggregation windows

- Minute / hour / day / week granularities run on Celery Beat
  schedules.
- Heatmap aggregator runs at higher cadence (~per minute) to keep
  the live overlay accurate.

---

# Performance Design

### High-frequency event handling

- The hot path is **Redis-only**: integer `INCR` / hash `HINCRBY` per
  event. Postgres is **not** touched per event.
- Hot keys live for short windows (minutes) and are flushed by
  micro-batch roll-ups; no unbounded growth.
- The Celery roll-up tier reads from Redis (or replays from `AIEvent`
  if Redis was cold) and writes one row per bucket.

### Load balancing

- Backend stateless replicas behind the load balancer handle WebSocket
  fan-out and metric reads.
- Celery workers form **distinct pools** for roll-ups vs reports vs
  notifications so a slow report cannot starve the live tiles.
- Read-replica routing is used for the heavier dashboard queries;
  the primary is reserved for writes and real-time reads.

### Redis optimisation

- Keys are **namespaced and TTL'd** consistently.
- **Pipelining** and **MULTI** are used in the metric path so per-
  event work is one round-trip.
- **Pub/sub** channels are per branch / per topic class to keep
  fan-out small per subscriber.
- A **secondary Redis** instance is used for pub/sub only (separate
  from the cache instance) to isolate noisy-neighbour patterns at
  scale.

### WebSocket scaling

- WebSocket gateway replicas are stateless; they subscribe to Redis
  pub/sub topics and fan out to connected clients.
- A **sticky load-balancer** keeps a client on the same replica for
  the connection's lifetime but recovery is automatic on replica
  loss (client reconnects with offset and the gateway backfills).
- Per-connection rate limits prevent a misbehaving client from
  saturating a replica.

---

# Failure Handling

| Failure | Detection | Containment | Recovery |
|---------|-----------|-------------|----------|
| **Missing AI event** | Late-events monitor, gap detection in `event_id` sequence per camera | Tile shows `partial` badge; aggregate marks bucket as `incomplete` | Backfill from `AIEvent` if event eventually persists; otherwise accept the gap. |
| **WebSocket drop** | Client heartbeat | Client reconnects with last offset per topic | Gateway backfills missing events up to a bounded window; older gaps are reloaded via REST. |
| **Stale Redis counter** | TTL expiry / version mismatch | Tile reads Postgres aggregate for the bucket | Counter rebuilds on next event. |
| **Aggregator job failure** | Celery dead-letter | Job retried with backoff | Idempotent on `(scope, bucket_start, granularity)` so retries are safe. |
| **Postgres replica lag** | Lag metric exceeds budget | Reads transparently fall back to primary for time-sensitive tiles | Lag normalises; replica catches up. |
| **AI pipeline delay** | `produced_at − occurred_at` p95 exceeds budget | UI tags affected tiles with "AI delayed"; tiles continue using the latest closed bucket | Pipeline recovers; live tile resumes. |
| **Data inconsistency (UI vs DB)** | Drill-down audit | UI shows a "Refresh" affordance; one source of truth is always Postgres | User can hard-refresh; the cache invalidates. |
| **Permission revoked mid-session** | WebSocket gateway hot-revoke | Affected subscriptions closed; UI prompts re-auth | User re-authenticates; tiles recompose per new scope. |

### Cardinal rule

- A failure in the analytics layer **MUST NEVER** affect transactional
  state. Carts, orders, payments, and inventory continue without
  degradation. The dashboard simply shows less detail.

---

# Business Value

### How analytics improves retail decisions

- **Staffing.** Hour-by-hour footfall + queue + wait metrics show
  when extra cashiers / floor staff produce the highest impact.
- **Layout.** Heatmaps reveal cold zones (poor footfall) and
  congested zones (poor flow); operators move endcaps, change
  signage, and re-test.
- **Assortment.** Interaction-to-purchase ratios distinguish
  *attention-grabbing-but-not-buying* SKUs from *unobserved-but-
  selling* ones — both are signals for re-merchandising.
- **Promotions.** Pre / during / post comparisons isolate the lift
  of a promotion against a control window or branch.

### Product placement optimisation

- The platform highlights:
  - Products with **high pick / low buy** (presentation or pricing
    problem).
  - Products with **low pick / high revenue** (worth a better
    location).
  - **Co-pick** clusters (products often picked together) → cross-
    merchandising opportunities.

### Loss-prevention insights

- Branch-level shrinkage indicators combine `TheftDetected`,
  `TheftSuspected`, and inventory variance.
- Time-of-day and zone-level patterns drive coverage decisions
  (camera angle, staff posting).
- Per-category loss rates inform packaging / tagging investments.

### Customer-experience insights

- Wait-time and queue-amber distributions, per cashier, per shift.
- Dwell vs conversion at the entrance, the apparel zone, the
  checkout aisle.
- Repeat-customer recognition (consented) drives loyalty programs.

### Anti-goals (deliberately not in this layer)

- Building a *general-purpose* BI tool. Reporting and ad-hoc
  analytics belong in `38_REPORTING.md`; this document is the
  **operational dashboard** layer.
- Letting the dashboard mutate AI, cart, inventory, or order state
  beyond its narrow set of audited operator actions.
- Storing identifiable shopper data inside aggregates.

---

# Future Enhancements

### Visualisation

- **3-D floor visualisations** with per-shelf heatmaps.
- **Time-scrubber** for replaying a busy hour from the dashboard.
- **Per-employee dashboards** (privacy-respecting; manager-only
  drill-down).
- **Mobile-friendly manager app** with the alerts panel and live
  tiles.

### Analytics

- **Real-time anomaly detection** on KPIs (footfall, wait, sales)
  with model-driven alerts.
- **What-if simulator** — apply a change (open one extra register,
  move a category) against historical traffic to estimate impact.
- **Cross-branch benchmarks** — same-format peer-branch comparisons
  with rank percentiles.
- **Forecasting** — short-horizon (next hour / next day) traffic and
  sales forecasts.

### Data platform

- **External BI export** — published data marts (Parquet / DuckLake)
  for warehouse use.
- **Optional TimescaleDB / column store** for very large tenants if
  partition maintenance becomes a burden.
- **Differential-privacy** noise on published aggregates released to
  third parties.

### Operations

- **Self-service tile builder** for branch managers (within a fixed
  metric whitelist).
- **Per-tenant alert routing rules** integrating with paging tools.
- **Audit-grade BI** with signed snapshots of dashboard state for
  governance reviews.

### Anti-goals (deliberately not on the plan)

- Tracking individuals' movements in real time on a map ("Where is
  Customer 123 right now?") — even with consent.
- Embedding raw-event firehoses inside the SPA (the SPA receives
  aggregated, permissioned deltas).
- Live mutation of business state from analytics tiles.
- Shipping a custom OLAP engine — Postgres aggregates + an optional
  warehouse export cover v1 and v2 needs.

---

*This document is the canonical Dashboard, Analytics & Heatmap design.
Any change to the analytics pipeline, KPI catalogue, heatmap model, or
visualisation strategy requires a PR that updates **only this file**
(and, when needed, an ADR explaining the rationale).*
