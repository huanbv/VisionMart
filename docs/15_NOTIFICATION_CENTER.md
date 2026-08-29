# VisionMart — Event System, Notification Center & Integration Hub

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/15_NOTIFICATION_CENTER.md`
> **Owner:** Lead Platform Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** platform-integration **design** only. No code, no APIs,
> no DDL, no framework-specific instructions. Where this document
> conflicts with implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract §2.3](ARCHITECTURE_CONTRACT.md#23-event-driven-design) ·
> [Domain Model — Event & Notification](DOMAIN_MODEL.md) ·
> [System Design — Event System](SYSTEM_DESIGN.md) ·
> [AI Overview](20_AI_OVERVIEW.md) ·
> [Cart Engine](26_CART_ENGINE.md) ·
> [Dashboard & Analytics](37_DASHBOARD.md) ·
> [Authentication](13_AUTHENTICATION.md) ·
> [WebSocket](16_WEBSOCKET.md) ·
> [ADR-014 Future Event Bus](adr/ADR-014-future-event-bus.md)

---

# Event System Overview

VisionMart is built **event-first**. Every observable change of state
(an AI detection, a cart line added, a camera going offline, an order
captured) becomes a **domain event** that the rest of the platform
reacts to. The Event System is the spine that:

1. **Centralises** the flow of those events through one logical bus
   ([ADR-014](adr/ADR-014-future-event-bus.md)).
2. **Routes** them to internal consumers (Cart, Inventory,
   Analytics, Notification, Dashboard, Audit, AI feedback).
3. **Notifies** the right humans on the right channels via the
   Notification Center.
4. **Integrates** with external systems through a controlled
   Integration Hub (webhooks, signed deliveries, future-ready
   subscription model).

### Cardinal rules

- **One canonical event schema.** Every event everywhere uses the
  same envelope (`event_id`, `event_type@vN`, `occurred_at`,
  `produced_at`, scope, payload, `correlation_id`).
- **At-least-once delivery; idempotent consumers.** Duplicates are
  inevitable; consumers handle them by dedup on `event_id`.
- **AI proposes; backend decides.** AI events are **inputs** to
  backend application services, never direct mutations of business
  tables ([AI Overview](20_AI_OVERVIEW.md#ai-system-overview)).
- **Cross-module communication is event-only or via published
  application services.** Direct ORM relationships across module
  boundaries are forbidden
  ([Architecture Contract §2.5](ARCHITECTURE_CONTRACT.md)).
- **Pluggable transport.** The current `InMemoryEventBus` is
  swappable for Redis Streams / RabbitMQ / Kafka without changing
  domain code or consumer code.

### Canonical flow

```
[AI Engine]                  [Backend application services]
        │                                │
        │ AIEvent                        │ DomainEvent
        ▼                                ▼
[AI Event Gateway] ───── persist ───► [EventBus]
        │                                │
        │ validation, scope check        │ fan-out to subscribed handlers
        ▼                                ▼
[EventBus]                       ┌──────────────┐
        │                        │  Consumers   │
        │                        │              │
        │                        │  Cart        │
        │                        │  Inventory   │
        │                        │  Analytics   │
        │                        │  Notification│
        │                        │  Dashboard   │
        │                        │  Audit       │
        │                        │  Integration │
        │                        └──────────────┘
        ▼
[Event Persistence]
   - AIEvent (partitioned)
   - DomainEvent outbox (when used)
   - DeliveryAttempt audit
```

### Producer / consumer model

| Producer | Typical events |
|----------|----------------|
| AI Engine | `ProductPickedUp`, `CustomerDetected`, `QueueDetected`, `TheftDetected`, `ShelfBecameEmpty`, `TrackingSessionStarted/Ended`, `SnapshotCaptured` |
| Cart application service | `CartCreated`, `CartUpdated`, `CartAbandoned`, `CheckoutInitiated`, `CartConverted` |
| Order application service | `OrderCreated`, `OrderRefunded`, `PaymentCaptured`, `PaymentFailed` |
| Inventory application service | `InventoryReserved`, `InventoryReleased`, `InventoryCommitted`, `StockMovementRecorded`, `LowStockTriggered` |
| Camera application service | `CameraRegistered`, `CameraOnline`, `CameraDegraded`, `CameraOffline`, `CameraReassigned` |
| Identity / Auth | `auth.login.succeeded/failed`, `auth.refresh.reuse_detected`, `role.assigned/revoked` |
| System / Health | `service.started`, `service.ready`, `service.unhealthy`, `model.deployed` |
| Analytics | `KPIUpdated`, `HeatmapUpdated`, `ReportGenerated` |

| Consumer | Typical interests |
|----------|-------------------|
| Cart Engine | `ProductPickedUp/Returned`, `CustomerDetected`, `TheftSuspected` |
| Inventory | `OrderCreated`, `StockMovementRecorded`, `ShelfBecameEmpty` |
| Notification Center | almost everything — gated by routing rules |
| Analytics | All AI events + transactional events for aggregates |
| Dashboard (via WebSocket Gateway) | Subset relevant to subscribed topics |
| Audit | Sensitive transitions (auth, refunds, role changes, model deploy) |
| Integration Hub | Per tenant subscription |
| AI Engine | `InventoryCommitted`, `CatalogChanged`, `ModelDeployed` (cache refresh signals) |

---

# Event Categories

> All events use the same envelope; categories below are a *taxonomy*
> for routing, observability, and access control — not a separate
> schema per group.

### AI events

| Event | Meaning |
|-------|---------|
| `CustomerDetected` | Recognised customer (with consent) entered the field of view. |
| `ProductDetected` *(internal, rarely published)* | Recognition completed for a product crop. |
| `ProductPickedUp`, `ProductReturned`, `ProductSwapped` | Smart cart cues. |
| `MotionDetected` | Motion in a zone outside business hours / outside ROI. |
| `QueueDetected`, `QueueRecovered` | Checkout / queue zones. |
| `ShelfBecameEmpty`, `ShelfRestocked`, `PlanogramMismatch` | Shelf-level inventory AI. |
| `TheftSuspected`, `TheftDetected` | Loss-prevention AI. |
| `TrackingSessionStarted`, `TrackingSessionEnded` | Per-camera shopper tracks. |
| `SnapshotCaptured` | Evidence frame stored in MinIO. |

### Business events

| Event | Meaning |
|-------|---------|
| `CartCreated`, `CartUpdated`, `CartAbandoned`, `CartLocked`, `CartUnlocked`, `CartConverted` | Smart Cart lifecycle. |
| `OrderCreated`, `OrderRefunded`, `OrderCancelled` | Order lifecycle. |
| `PaymentCaptured`, `PaymentFailed`, `RefundIssued` | Payment lifecycle. |
| `InventoryReserved`, `InventoryReleased`, `InventoryCommitted`, `StockMovementRecorded`, `LowStockTriggered`, `StocktakeOpened/Closed` | Inventory lifecycle. |
| `ProductCreated/Updated/Deleted`, `CategoryUpdated` | Catalog changes (drive AI cache refresh). |
| `CustomerCreated/Updated`, `ConsentGranted/Withdrawn` | Customer lifecycle (drive privacy actions). |
| `EmployeeClockedIn/Out`, `EmploymentRecordCreated` | Staff lifecycle. |

### System events

| Event | Meaning |
|-------|---------|
| `CameraRegistered`, `CameraOnline`, `CameraDegraded`, `CameraOffline`, `CameraError`, `CameraReassigned`, `CameraDisabled/Enabled` | Camera infrastructure. |
| `ServiceStarted`, `ServiceReady`, `ServiceUnhealthy`, `ServiceShuttingDown` | Per-process lifecycle (for observability). |
| `ModelDeployed`, `ModelRolledBack` | AI model registry. |
| `SystemError` | Uncaught exceptions at the service boundary. |

### Analytics events

| Event | Meaning |
|-------|---------|
| `HeatmapUpdated` | Heatmap tile aggregate refreshed for a window. |
| `KPIUpdated` | One or more KPIs changed for a branch / org. |
| `ReportGenerated` | Scheduled or on-demand report finished. |
| `BucketClosed` | A time-bucket aggregate transitioned from partial to closed. |

### Auth & security events

| Event | Meaning |
|-------|---------|
| `auth.login.succeeded/failed`, `auth.locked`, `auth.refresh.reuse_detected`, `auth.session_revoked` | Authentication actions. |
| `authz.permission_denied`, `authz.branch_denied`, `authz.cross_tenant_attempt` | Authorisation refusals. |
| `apikey.created/revoked`, `role.assigned/revoked` | Identity admin actions. |
| `consent.granted/withdrawn` | Customer consent state changes. |

> Every event in every category has a stable `event_type@vN` value.
> Adding a field is **additive**; removing or renaming a field
> requires a new version.

---

# Event Processing Pipeline

### Stages

```
[Producer]
     │ build event with envelope
     ▼
[Ingestion]
     │  - AI Event Gateway (for AI Engine)
     │  - Direct EventBus publish (for backend services)
     ▼
[Validation]
     │ schema/version, scope (org/branch/camera), timestamp skew,
     │ confidence ranges, ownership (camera belongs to tenant)
     ▼
[Normalization]
     │ enforce UTC, canonical units, branch currency,
     │ id formats, trim payload to the schema
     ▼
[Enrichment]
     │ derive denormalised hints (product name, zone label) when
     │ the consumer benefits; never enrich with PII
     ▼
[Persistence (where required)]
     │ AIEvent + DetectionResult sample (partitioned)
     │ DomainEvent outbox (when transactional outbox is used)
     ▼
[Dispatching]
     │ Hand to EventBus → fan-out to subscribed handlers
     ▼
[Consumers]
     │ each consumer is idempotent on event_id
```

### Synchronous vs asynchronous

| Path | Mode | Examples |
|------|------|----------|
| Aggregate-mutating operations triggered by a single request | **Sync** within one Postgres transaction | Cart line add → reservation; checkout → order + payment + stock movement |
| Cross-context fan-out after a transaction commits | **Async** via EventBus | `OrderCreated` → Notification, Analytics, Audit, Integration Hub |
| Real-time UI delta | **Async** through the WebSocket gateway | Live tile updates |
| External webhook delivery | **Async** with retries and DLQ | Webhook to a tenant's ERP |

The hard rule: **never block a transaction on a network side-effect**
(no in-transaction webhook posts, no in-transaction email sends). All
out-of-process effects are produced from committed events.

### Queue strategy

- **Foreground** path: the EventBus dispatches handlers immediately;
  Redis-backed pub/sub is used for fan-out across replicas.
- **Background** path: handlers that do work (notifications, analytics
  roll-ups, integration deliveries) enqueue Celery tasks on
  **dedicated queues** so a slow consumer cannot starve other
  workloads.
- All internal queues are **bounded**; backpressure is observable
  via metrics; severity-aware shedding applies.

### Transactional outbox (when required)

- For correctness-critical fan-out (e.g. webhook delivery of
  `OrderCreated`), the application service writes the event to an
  **outbox table** inside the same transaction as the business
  write.
- A relay process reads the outbox and publishes to the EventBus /
  external broker. This guarantees that "the order exists ⇔ the
  event will be delivered".

---

# Notification Center

### Notification types

| Type | Examples |
|------|----------|
| **Real-time alerts** | Theft, queue red, camera offline, low-stock at threshold |
| **System alerts** | Service unhealthy, AI degraded, backlog growing |
| **Business alerts** | Order failed payment, refund issued, large order, return spike |
| **AI alerts** | New model deployed, AI confidence below floor, planogram mismatch |
| **Operational digests** | Daily summary, weekly report, low-stock digest |

### Channels (v1 + roadmap)

| Channel | v1 | Notes |
|---------|----|-------|
| **WebSocket (in-app)** | ✅ | Primary channel for live dashboard alerts. |
| **Email** | ✅ | Transactional + digests. |
| **Webhook** | ✅ | For integration consumers (signed; see §Integration Hub). |
| **SMS** | future | Pluggable provider; opt-in per tenant. |
| **Zalo / Telegram / Slack / Teams** | future | Channel adapters with the same routing engine. |
| **Mobile push (FCM/APNs)** | future | Customer companion app + manager app. |

> Each channel is an **adapter** behind a common interface. Adding a
> channel is configuration + an adapter, not a notification-engine
> rewrite.

### Notification model

- A **Notification** is one logical message instance: `recipient`,
  `channel`, `type`, `title`, `body`, `payload`, `priority`,
  `correlation_id`, `created_at`, `read_at`.
- A **DeliveryAttempt** records each per-channel send (`status`,
  `attempted_at`, `response_code`, `next_retry_at`).
- A **Subscription** registers an external endpoint (webhook URL,
  HMAC secret, event filter) for a tenant.
- A **NotificationPreference** lets users opt in/out per category and
  channel, with quiet hours.

### Routing pipeline

```
[Domain / AI Event]
     │
     ▼
[Notification Rules]
     │ resolve: priority, audience (roles / users / branch),
     │ channels (per user preference + tenant policy),
     │ rate-limit window, quiet hours
     ▼
[Channel Adapters]
     │ in-app push, email queue, webhook queue, ...
     ▼
[DeliveryAttempt records + retries + DLQ]
```

### Templates and localisation

- Every notification type has a **template** with localised
  variants. The platform renders templates server-side; the SPA
  receives the rendered title/body plus structured payload for
  drill-down.
- Templates carry stable **template ids** so customers can replace
  defaults (subject to platform-defined guardrails).

---

# Notification Triggers

### Trigger → routing matrix (canonical defaults)

| Event | Type | Default priority | Audience | Channels (default) |
|-------|------|------------------|----------|--------------------|
| `TheftDetected` | AI alert | **Critical** | Branch manager + loss-prevention role | WebSocket + email; webhook to security partner if subscribed |
| `TheftSuspected` | AI alert | High | Floor supervisor | WebSocket |
| `CameraOffline` (> grace) | System alert | High | Branch manager + ops | WebSocket + email |
| `CameraDegraded` | System alert | Medium | Ops | WebSocket |
| `LowStockTriggered` | Business alert | Medium | Branch manager + stock role | WebSocket + email digest |
| `QueueRed` | Operational | High | Cashier supervisor + branch manager | WebSocket |
| `QueueAmber` | Operational | Medium | Cashier supervisor | WebSocket |
| `HighTrafficDetected` | Analytics | Medium | Branch manager | WebSocket |
| `PaymentFailed` | Business alert | High | Cashier on shift + manager | WebSocket |
| `OrderRefunded` | Business alert | Medium | Manager | WebSocket + email |
| `ModelDeployed` / `ModelRolledBack` | System | Medium | Org admin + AI ops | WebSocket + email |
| `ServiceUnhealthy` | System | High | Platform ops | WebSocket + email + webhook to monitoring |
| `auth.refresh.reuse_detected` | Security | **Critical** | Affected user + org admin | WebSocket + email |
| `authz.cross_tenant_attempt` | Security | **Critical** | Platform ops | Email + webhook |
| `ConsentWithdrawn` | Privacy | High | Org privacy role | WebSocket + email |

### Priority levels (canonical)

| Priority | Meaning | Treatment |
|----------|---------|-----------|
| **Critical** | Safety / security / financial / compliance impact | Bypasses quiet hours; multi-channel; auto-escalates if not acknowledged within SLA |
| **High** | Operationally urgent | Respects quiet hours for non-on-call recipients; one or two channels |
| **Medium** | Operational hygiene | Quiet-hours-respecting; batched into digests when allowed |
| **Low** | Informational | In-app only by default; usually digested |

### Rate-limiting / anti-storm rules

- Per-event-type **cooldown** windows prevent repeat alerts (already
  enforced upstream by AI rule cooldowns for AI events).
- Per-recipient **digest** option collapses a category into a single
  periodic email instead of one-per-event.
- Per-tenant **alert budgets** trip a circuit breaker that downgrades
  Medium and Low to in-app only when exceeded; Critical and High are
  never throttled.

### Acknowledgement and escalation

- The dashboard exposes an **acknowledge** action on each alert
  (audited as `notification.acknowledged`).
- Critical alerts have an **SLA timer**; unacknowledged Critical
  alerts re-route to the next escalation tier after the SLA.

---

# Integration Hub

### External-facing surface

The Integration Hub is the **only** place external systems can:

- **Consume** VisionMart events (via webhooks or a future broker
  bridge).
- **Push** data into VisionMart (catalogue sync, employee sync,
  inventory adjustments) through versioned REST APIs.

It is **not**:

- A direct database connector.
- A bypass for RBAC, multi-tenant isolation, or audit.

### Webhook system

- A tenant creates a **Subscription** with: target URL, **HMAC
  secret**, event filter (types, branches, optional confidence
  floor), retry policy, environment tag.
- The hub delivers events as signed HTTPS POSTs with:
  - `X-VisionMart-Event` (`event_type@vN`),
  - `X-VisionMart-Event-Id` (idempotency key),
  - `X-VisionMart-Signature` (HMAC over body + timestamp),
  - `X-VisionMart-Timestamp` (anti-replay window),
  - `X-VisionMart-Delivery` (delivery attempt id),
  - body = canonical event envelope.
- Receivers verify the HMAC and dedupe on `X-VisionMart-Event-Id`.

### Delivery semantics

- **At-least-once** delivery with **exponential backoff** retries
  (e.g. 30 s → 1 m → 5 m → 30 m → 2 h … capped, total budget
  ~24 h).
- After the retry budget, the delivery moves to a **Dead Letter
  Queue (DLQ)**; subscribers can re-drive from the DLQ within a
  bounded window.
- A subscription with persistent failures is **auto-disabled** and
  the tenant admin is alerted.

### Inbound integrations

- Inbound endpoints are versioned (`/api/v1/...`), require an
  API key with scopes (`integration.catalog.write`,
  `integration.inventory.adjust`, ...), and validate at the
  application boundary like any other request.
- Inbound payloads carry an **idempotency key** for safe retries.

### Event subscription model

- Per tenant: a tenant can have many subscriptions; events match
  the OR of all subscriptions whose filters apply.
- Per role / per user (in-app): users subscribe in the UI to
  categories; these are stored as `NotificationPreference` rows.
- Per integration (machine): subscriptions are managed via the
  admin UI; subscription changes are audited.

### Future broker bridges

- The hub abstracts the transport so a tenant **MAY** be offered a
  message-broker bridge (Kafka topic, RabbitMQ queue, AWS EventBridge)
  in addition to webhooks. The internal event taxonomy is the same.

---

# Module Communication

### Cardinal rule

- **Cross-module communication is event-driven or via published
  application services.** Modules **MUST NOT** import each other's
  ORM models or join across module tables in raw SQL.

### Flow per module

| Module | Publishes | Subscribes / consumes |
|--------|-----------|------------------------|
| AI Engine | `AIEvent` (via the gateway) | `InventoryCommitted`, `CatalogChanged`, `ModelDeployed`, `ConsentWithdrawn` (cache refresh) |
| Cart | `Cart*` | `ProductPickedUp/Returned`, `CustomerDetected`, `TheftSuspected` |
| Order | `Order*`, `Payment*`, `RefundIssued` | `CartConverted`, `CheckoutInitiated` |
| Inventory | `Inventory*`, `StockMovementRecorded`, `LowStockTriggered`, `Stocktake*` | `OrderCreated`, `RefundIssued` |
| Camera | `Camera*` | `ServiceStarted` (probe scheduling) |
| Notification Center | `notification.sent`, `notification.failed` | nearly all categories (gated) |
| Analytics | `KPIUpdated`, `HeatmapUpdated`, `BucketClosed`, `ReportGenerated` | AI + business + system events |
| Dashboard / WebSocket Gateway | (re-broadcasts) | per-topic subscriptions |
| Audit | none (it is a consumer) | sensitive transitions |
| Integration Hub | `webhook.delivered`, `webhook.failed`, `webhook.dlq` | per-tenant subscription filters |

### Decoupling strategy

- Producers know **nothing** about consumers.
- Consumers depend on **event contracts**, not on producer
  implementations.
- Schema evolution is **additive**; version bumps coexist for a
  documented deprecation window.
- Synchronous cross-module calls (rare) go through **published
  application service interfaces** — not direct repository calls and
  not ORM joins.

---

# Event Storage

### What is persisted

| Stream | Storage | Retention |
|--------|---------|-----------|
| **AI events** (`AIEvent`) | Postgres, monthly partitioned, indexed for query | 90 days hot, aggregates kept; older partitions archived |
| **Detection samples** (`DetectionResult`) | Postgres, monthly partitioned | 30 days hot |
| **Outbox / domain events** (when used) | Postgres, short-lived | until successful publish + grace |
| **Delivery audit** (`DeliveryAttempt`) | Postgres | per audit retention |
| **System events** | Structured JSON log stream (Loki / vendor equivalent) | per log retention |
| **Hot recent feed** (per-camera / per-branch) | Redis, short TTL | minutes |

### Cache layer

- The dashboard's WebSocket gateway and the AI Engine consult a
  **Redis** mirror of the *most recent* events per topic for fast
  backfill on reconnect.
- Redis is **not** the authoritative store for events; loss of
  Redis degrades reconnect latency but never loses persisted
  events.

### Event replay (future-ready)

- The AI event tables and the outbox are designed so events can be
  **re-played** to a subset of consumers (e.g. re-build analytics
  aggregates from a window) with bounded effort.
- Replay is an **operator action**, audited; it is not a normal user
  flow.

### Archival

- Closed monthly partitions are eligible for **detach + Parquet
  export** to MinIO / S3 cold storage.
- Per-tenant policy can extend retention within platform-allowed
  bounds; archival operations are audited.

---

# Real-time Delivery

### Channels

- **WebSocket** is the primary real-time channel for the dashboard,
  cashier UI, and (future) customer / manager mobile apps
  ([16_WEBSOCKET.md](16_WEBSOCKET.md)).
- **Webhook** delivers events to external systems.
- **Email / SMS / chat** are not strictly real-time; they ride the
  Notification Center channels with their own SLAs.

### Latency targets (p95)

| Hop | Budget |
|-----|--------|
| Producer → EventBus | ≤ 30 ms |
| EventBus → consumer (in-process) | ≤ 50 ms |
| Consumer → WebSocket fan-out | ≤ 50 ms |
| End-to-end event → user UI (in-app alert) | ≤ 200 ms |
| Webhook first attempt | ≤ 5 s after event commit |
| Email queue first attempt | ≤ 30 s |

### Delivery guarantees

- **In-process EventBus:** at-least-once with idempotent handlers.
- **WebSocket fan-out:** best-effort; clients reconnect with a
  monotonic offset per topic and the gateway backfills a bounded
  window. Consumers must therefore be idempotent on `event_id`.
- **Webhook:** at-least-once with retries and DLQ; never
  exactly-once (industry standard). The signed payload + `event_id`
  let receivers dedupe.
- **Audit writes (sensitive transitions):** synchronous and
  exactly-once relative to their owning transaction (because the
  audit row is in the same transaction).

---

# Scalability Design

### High-throughput handling

- Hot event paths (per-frame detections, per-event Redis counters)
  use **bounded, sharded** Redis structures with `EXPIRE` TTLs.
- Per-event Postgres writes are avoided on the hottest path; only
  **sampled** `DetectionResult` rows are persisted, while **all**
  high-signal `AIEvent`s are persisted (partitioned).
- Queue-backed processing isolates slow consumers from fast ones
  (per-queue concurrency).

### Broker abstraction (current and future)

- v1 uses an **`InMemoryEventBus`** plus Redis pub/sub for cross-
  replica fan-out.
- v2 swaps the in-memory bus for a real broker (Redis Streams,
  RabbitMQ, Kafka, NATS) without changes to producer or consumer
  code ([ADR-014](adr/ADR-014-future-event-bus.md)).
- The choice is per **deployment**, not per **module**.

### Horizontal scaling

- Backend replicas are stateless; the EventBus is either in-process
  (small) or broker-backed (large). Adding replicas scales
  throughput linearly.
- Consumers can be partitioned by **scope keys** (e.g. by
  `organization_id` or `branch_id`) for ordered processing within
  a partition; cross-partition order is not guaranteed and
  consumers don't depend on it.

### Load balancing

- WebSocket connections use a **sticky load balancer** for the
  connection lifetime; the gateway re-fans Redis pub/sub regardless
  of which replica a subscriber is on.
- Celery workers belong to **named queues** sized independently
  (notifications, analytics roll-ups, integration deliveries,
  reports).

---

# Failure Handling

### Event loss

- **In-process bus:** if a replica crashes mid-fan-out, undelivered
  in-flight events are lost. Two mitigations:
  - **Transactional outbox** for fan-outs that must reach external
    consumers (webhooks).
  - **Idempotent producers** for analytics so a re-trigger on the
    next event re-converges aggregates.
- **Broker bus:** durable subscriptions and consumer offsets
  guarantee at-least-once.

### Duplicate handling

- All consumers are **idempotent on `event_id`** (and on `(scope,
  bucket_start)` for aggregates).
- WebSocket gateway dedupes per-connection (a backfill window can
  re-deliver an already-seen id; the client filters).

### Retry strategy

- Internal consumers: **bounded retries with exponential backoff**,
  jitter, and a circuit breaker that opens after sustained failure.
- Webhooks: documented retry schedule (see §Integration Hub);
  failures move to DLQ after budget.
- Notification channels (email, SMS): provider-recommended retry
  policy; permanent failures bubble back as `notification.failed`.

### Dead letter queue

- Failed messages move to a **DLQ** per channel / per consumer.
- DLQs are **bounded** and monitored; growth is itself an alert.
- Operators can inspect, redact (where allowed), and re-drive
  messages from the DLQ; every action is audited.

### Service health & graceful shutdown

- A consumer that detects upstream degradation **slows** its read
  rate and emits `ServiceUnhealthy`.
- On shutdown, consumers drain their in-flight work before
  releasing the queue; new work routes to surviving replicas.

---

# Security Model

### Event authorisation

- Every event carries `organization_id` (and `branch_id` /
  `camera_id` where applicable).
- A consumer that fans events to humans (WebSocket, email,
  webhooks) **MUST** re-check the recipient's scope before
  delivering — exactly the same RBAC that REST uses
  ([Authentication §Multi-Branch Security](13_AUTHENTICATION.md#multi-branch-security)).
- A subscriber **never** sees events outside its allowed scope, even
  by topic name.

### API authentication for integrations

- Inbound integration calls authenticate with **API keys** (service
  accounts) scoped to the operations they need.
- Keys are **hashed** server-side, **rotatable**, and **auditable**
  ([Authentication](13_AUTHENTICATION.md)).

### Webhook security

- Each subscription has its own **HMAC secret**; the platform signs
  every delivery and the receiver verifies the signature.
- Anti-replay: the receiver checks `X-VisionMart-Timestamp` is within
  a window (e.g. 5 minutes).
- Deliveries always go over **HTTPS**; HTTP URLs are rejected at
  subscription time.
- Subscription create/update/delete are audited.

### Role-based event access (in-app)

- Notification routing rules are bounded by **roles + branch
  scope**; a `cashier` will not see `super_admin`-level alerts.
- WebSocket topic subscriptions are permission-checked at
  subscribe time, not at session creation
  ([WebSocket](16_WEBSOCKET.md)).

### Privacy in events

- Events **never** carry passwords, hashed credentials, JWTs, raw
  payment data, or biometric vectors.
- Customer identifiers are `customer_id` only; receivers fetch PII
  separately if (and only if) permitted.
- Snapshot URLs in events are **short-lived signed URLs** issued at
  delivery time by the producer; the URL alone is not authority.

---

# Observability

### Event logging

- Every event delivery (in-app, webhook, channel) writes a
  **structured log line** with `correlation_id`, `event_id`,
  `event_type@vN`, `recipient` (where applicable), `outcome`, and
  latency.
- Logs are **JSON**, shipped to the central log store; PII and
  secrets are scrubbed at the source.

### Metrics

- **Producer metrics:** events produced per type per tenant per
  minute; produce errors.
- **Bus metrics:** queue depths, fan-out latencies, dead-letter
  growth.
- **Consumer metrics:** handled events per second, handler latency
  histograms, error rates, retry counts.
- **Notification metrics:** per-channel send/failure rates, queue
  depths, alert acknowledgement times, SLA breaches.
- **Webhook metrics:** per-subscription success/failure, p95/p99
  delivery times, retries, DLQ size.

### Traceability

- Every event carries a **`correlation_id`** propagated end-to-end
  from the originating HTTP request, the AI frame, or the scheduled
  job.
- Logs, audit records, and notifications all carry the same
  `correlation_id` so a single shopper interaction can be traced
  from frame to email.
- `event_id` is the *primary key* of the event; `correlation_id` is
  the *thread* binding many events to one cause.

### Debugging strategy

- Operator UI for browsing recent events per tenant / branch /
  topic, with full envelope and payload (scrubbed of secrets).
- Operator UI for inspecting DLQs and re-driving messages.
- Operator UI for replaying events to a single consumer in a
  staging environment, never in production.

### SLOs (illustrative; tuned per environment)

- **Bus availability:** 99.95 % monthly.
- **Notification deliverability:** Critical / High ≥ 99.9 %
  attempted within SLA; Medium / Low ≥ 99 %.
- **Webhook deliverability:** ≥ 99 % within 24 h to non-failing
  endpoints.
- **End-to-end latency (event → user):** p95 ≤ 200 ms.

---

# Business Value

### Why event-driven matters for retail AI

- **Real-time is the product.** A queue alert that arrives 30 s late
  is useless; a smart-cart update that arrives 2 s late looks
  broken. An event-first architecture is the only way to keep
  perception, transactions, and visualisation in sync at retail
  pace.
- **Modular evolution.** New capabilities (loyalty, promotions,
  customer mobile) attach as **consumers** without rewriting the
  producers.
- **Independent scaling.** Per-consumer queues let "the analytics
  thing being slow today" never affect cart latency.
- **Auditable causality.** With `correlation_id` and `event_id`,
  every business outcome is explainable back to its inputs.

### How notifications improve operations

- **Faster response** to theft, queues, low-stock, and downtime.
- **Quieter on-call** via priority + cooldown + digest rules.
- **Higher accountability** through acknowledgement, escalation, and
  audit.

### How integrations enable SaaS monetisation

- **Per-tenant subscriptions** make VisionMart a *platform* — ERPs,
  POS, loss-prevention partners, marketing tools, BI warehouses all
  plug in through the same hub.
- **Stable event contracts** plus webhook SLAs are the foundation
  of a **partner ecosystem**: integrators ship integrations once;
  every VisionMart tenant can adopt them.
- **Tiered packaging** (number of subscriptions, broker bridge,
  custom SLAs) becomes a natural premium add-on.

---

# Future Enhancements

### Event platform

- **Native broker** (Kafka / NATS / RabbitMQ) as a deployment
  option for very high throughput tenants.
- **Schema registry** with automatic compatibility checks for every
  `event_type@vN`.
- **Tenant-scoped streams** with per-tenant retention and replay.
- **Outbox-everywhere** as the default for any cross-context fan-
  out that crosses a process boundary.

### Notifications

- **Smart routing** that learns per-user response patterns and
  re-routes alerts to the recipient most likely to act.
- **Multi-step playbooks** ("acknowledge in 60 s, else escalate to
  manager, else page on-call") configurable per tenant.
- **Customer-facing notifications** (mobile push, receipt email)
  with templates per tenant brand.

### Integration Hub

- **Marketplace** of partner integrations with one-click connect.
- **OAuth2 outbound** for partners that prefer it over webhooks.
- **Event bridges** to AWS EventBridge, Azure Event Grid, GCP
  Pub/Sub.
- **Bidirectional sync adapters** (e.g. catalog sync from
  ERP → VisionMart and orders VisionMart → ERP) using the same
  event contracts.

### Observability

- **Per-tenant SLO dashboards** for events and notifications.
- **Auto-investigation** that, on an SLO breach, surfaces the
  correlation_id of the slowest 1 % of events with the relevant
  log slice.

### Anti-goals (deliberately not on the plan)

- Letting external systems write directly to the database.
- Exactly-once semantics across networks (not a real thing).
- Hidden side-effects (no consumer should silently mutate state
  outside its module).
- Long-lived (> hours) webhook retries that pile up DLQ pressure.
- Treating the EventBus as a request/response RPC layer.

---

*This document is the canonical Event System, Notification Center, and
Integration Hub design. Any change to event categories, processing
pipeline, notification routing, or integration semantics requires a PR
that updates **only this file** (and, when needed, an ADR explaining
the rationale).*
