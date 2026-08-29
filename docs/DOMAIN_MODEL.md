# VisionMart — Domain Model (DDD Core)

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/DOMAIN_MODEL.md`
> **Owner:** Lead Domain Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope of this document:** business modelling only. No code, no database
> schema, no APIs. Where this document conflicts with implementation, this
> document wins and the implementation **MUST** be refactored.

---

# Domain Overview

VisionMart is a **multi-tenant, multi-branch, AI-driven retail operations
platform**. The business problem it solves is: *turn ordinary store cameras
and an ordinary POS workflow into an intelligent, real-time, end-to-end
retail operations layer.*

The domain is composed of three thematic pillars:

1. **Retail operations** — Organizations, Branches, Employees, Customers,
   Catalog, Inventory, Cart & Order, Payment.
2. **Vision intelligence** — Cameras, AI pipelines (detection, tracking,
   recognition, heatmap, queue, theft), and the events they emit.
3. **Insight & coordination** — Notifications, Analytics, Reporting, Audit.

The whole system is described as a set of **Bounded Contexts** that
communicate through **published application services** and **domain
events**, never through shared internal state.

### Ubiquitous Language (selected, shared terms)

| Term | Meaning across contexts |
|------|-------------------------|
| **Organization (Tenant)** | The contracting business; the top-level isolation boundary. |
| **Branch** | A physical store under an organization. |
| **Catalog Product** | The sellable definition (SKU, name, price). |
| **Inventory Item** | A stock balance of one product at one branch. |
| **Shopper** | A person physically present in a branch, identified by a track ID (anonymous by default). |
| **Customer** | A persistent, optionally identified shopper profile. |
| **Cart** | A work-in-progress collection of items, possibly AI-populated. |
| **Order** | A confirmed, immutable sale. |
| **Track** | A short-lived AI identity for a moving thing (person or product). |
| **Detection Event** | An immutable record that the vision pipeline observed something. |

Words that mean *different things in different contexts* (e.g. "item",
"recognition", "session") are explicitly scoped inside each context below.

---

# Bounded Contexts

The system is divided into 13 bounded contexts. Each one is the **single
owner** of its aggregates; no other context may read or mutate them
directly.

| # | Context | Mission | Strategic Type |
|---|---------|---------|----------------|
| 1 | **Identity & Access** | Who can do what. | Supporting |
| 2 | **Organization** | The tenant and its global settings. | Core (Tenancy) |
| 3 | **Branch Management** | Physical store sites and their config. | Core |
| 4 | **Product Catalog** | What the business sells. | Core |
| 5 | **Inventory** | How much of each product is at each branch. | Core |
| 6 | **Order & Cart** | The sale lifecycle, including AI-assisted carts. | Core |
| 7 | **Customer** | Persistent customer identities and consent. | Core |
| 8 | **Employee** | Staff records, roles in the field. | Supporting |
| 9 | **Camera** | Physical cameras and their health. | Core |
| 10 | **AI Processing** | Vision pipelines and the events they emit. | Core (Differentiating) |
| 11 | **Event & Notification** | Routing alerts to people and systems. | Supporting |
| 12 | **Analytics** | Aggregated business intelligence. | Supporting |
| 13 | **Reporting** | Scheduled, exportable business reports. | Supporting |

Contexts marked **Core (Differentiating)** are where VisionMart wins or
loses in the market.

---

# Entities

> **Convention.** Entities listed under a context are owned exclusively by
> that context. Cross-context references use **identifiers only** (e.g.
> `ProductId`, not a navigable Product reference).

### 1. Identity & Access Context

- **User** — a person who can authenticate.
- **Role** — a named bundle of permissions.
- **Permission** — an atomic capability (`order.refund`, `camera.read`, …).
- **Session** — a live authenticated session, revocable.
- **ApiKey** — a service-account credential.

### 2. Organization Context

- **Organization (Tenant)** — root of multi-tenant isolation.
- **OrganizationSetting** — overridable configuration owned by the tenant.

### 3. Branch Management Context

- **Branch** — a physical store location.
- **Zone** — a logical area inside a branch (entrance, checkout, aisle).
- **OperatingHours** — opening/closing windows of a branch.

### 4. Product Catalog Context

- **Product** — a sellable item.
- **Category** — a node in the product taxonomy tree.
- **ProductMedia** — images and gallery items attached to a product.

### 5. Inventory Context

- **InventoryItem** — stock balance of one product at one branch.
- **StockMovement** — an audited change to inventory (in / out / transfer /
  reservation / commit / release).
- **Stocktake** — a physical-count session with expected vs counted
  variances.

### 6. Order & Cart Context

- **ShoppingCart** — items being assembled (manually or by AI).
- **CartLine** — one line inside a cart.
- **Order** — a confirmed sale; immutable after payment.
- **OrderLine** — one line of a paid order; captures price at sale time.
- **Payment** — a settled payment instrument result for an order.
- **Refund** — a settled (full or partial) refund tied to an order.

### 7. Customer Context

- **Customer** — a persistent customer profile.
- **CustomerConsent** — the consent record for biometric processing.
- **FaceEmbeddingRef** — an opaque reference to a stored face vector (the
  vector itself is owned by AI Processing; this entity tracks its
  *registration* and *consent state*).
- **CustomerSegment** — a behavioural grouping (new / occasional / regular
  / VIP).

### 8. Employee Context

- **Employee** — a staff record.
- **EmploymentRecord** — hire/termination history and position changes.

### 9. Camera Context

- **Camera** — a physical camera registered to a branch.
- **CameraHealthState** — the most recent connectivity and frame-quality
  state.
- **CameraAIConfig** — the per-camera switch board for AI pipelines.

### 10. AI Processing Context

- **VisionPipeline** — a configured pipeline running on a camera
  (detection, tracking, recognition, heatmap, queue, theft).
- **Track** — a short-lived identity for a moving thing across frames.
- **DetectionEvent** — an immutable observation of an object/person in a
  frame.
- **RecognitionResult** — a labelled outcome (this track ID is `Product
  XYZ` at confidence `0.93`).
- **ModelRegistration** — the active model version per pipeline per tenant.
- **Snapshot** — a saved frame stored for incident or evidence purposes.

### 11. Event & Notification Context

- **Notification** — a single message to a user, role, or webhook.
- **NotificationPreference** — per-user channel and quiet-hours settings.
- **Subscription** — a webhook registration.
- **DeliveryAttempt** — the audit of one delivery attempt.

### 12. Analytics Context

- **FootfallAggregate** — per-branch/zone/hour counts.
- **DwellAggregate** — per-zone average dwell time per bucket.
- **ConversionAggregate** — visitors vs buyers per bucket.
- **QueueAggregate** — per-checkout queue length history.
- **HeatmapTile** — a heat value for a floor-plan tile per bucket.
- **StaffActivityAggregate** — per-employee productivity counts.

### 13. Reporting Context

- **Report** — a definition (template + parameters).
- **ReportRun** — the result of running a report once.
- **ScheduledReport** — a recurring report subscription.

---

# Value Objects

> **Convention.** Value objects are **immutable** and have no identity.
> Comparing two value objects of the same type with the same fields means
> they are the same value.

### Shared (allowed in every context)

- `OrganizationId`, `BranchId`, `UserId`, `EmployeeId`, `CustomerId`,
  `CameraId`, `ProductId`, `CategoryId`, `CartId`, `OrderId`, `TrackId`,
  `NotificationId`, `EventId`
- `Money { amount, currency }` — the only legal way to represent monetary
  values.
- `Quantity { value, unit }` — non-negative count.
- `Percentage { value }` — bounded `0..100`.
- `Confidence { value }` — bounded `0.0..1.0`, used by AI outputs.
- `TimeRange { start, end }`
- `TimestampUtc` — every domain timestamp is UTC.
- `AuditStamp { occurredAt, actorId }`

### Identity & Access

- `Email`, `PasswordHash`, `HashedToken`, `IpAddress`, `UserAgent`
- `PermissionCode` — canonical string like `inventory.adjust`.

### Organization & Branch

- `Slug` — URL-safe organisation/branch identifier.
- `Address { line1, line2, city, region, country, postalCode }`
- `Timezone`
- `BranchCode`
- `ZoneType` (enum: ENTRANCE, CHECKOUT, AISLE, STAFF, RESTRICTED)

### Catalog

- `Sku`, `Barcode`, `Currency`
- `ProductAttributes` — opaque, validated, key→primitive map.
- `Slug`

### Inventory

- `MovementReason` (enum: PURCHASE, SALE, RETURN, TRANSFER_IN,
  TRANSFER_OUT, ADJUSTMENT, RESERVATION, RELEASE, COMMIT, SHRINKAGE).
- `StockDelta` — signed integer with a reason.

### Cart & Order

- `OrderCode` — human-friendly per-tenant unique reference.
- `OrderStatus` (enum: PENDING, PAID, CANCELLED, REFUNDED).
- `CartStatus` (enum: ACTIVE, ABANDONED, CONVERTED, EXPIRED).
- `CartSource` (enum: MANUAL_POS, AI_VISION, MOBILE_APP, SELF_CHECKOUT).
- `Discount { type, value, scope }` — order-level or line-level.
- `PaymentMethod` (enum: CASH, CARD, QR, WALLET, OTHER).
- `LineItem { productId, quantity, unitPrice, discount, subtotal }`.

### Customer

- `ConsentScope` (enum: FACE_RECOGNITION, ANALYTICS, MARKETING).
- `ConsentRecord { scope, grantedAt, withdrawnAt? , source }`.

### Camera & AI

- `StreamUrl` — validated URI (rtsp/rtmp/http).
- `Resolution { width, height }`.
- `Fps` — bounded positive integer.
- `BoundingBox { x, y, width, height }`.
- `ObjectClass` — string label from the active model.
- `PipelineKind` (enum: DETECTION, TRACKING, PRODUCT_RECOGNITION,
  PERSON_REID, HEATMAP, QUEUE, THEFT, SHELF_OCCUPANCY).
- `ModelVersion { name, version, hash }`.
- `FrameRef { cameraId, timestamp, sequenceNumber }`.

### Notification & Reporting

- `NotificationChannel` (enum: IN_APP, EMAIL, SMS, WEBHOOK, PUSH).
- `NotificationPriority` (enum: LOW, NORMAL, HIGH, CRITICAL).
- `ReportFormat` (enum: PDF, XLSX, CSV).
- `CronExpression`.

---

# Aggregates

> **Convention.** Each aggregate has exactly one **Aggregate Root**. External
> code may reference only the root. The root enforces all invariants for
> objects inside its boundary, in a single transaction.

| Aggregate Root | Internals (entities & value objects bound to the root) | Invariants enforced by the root |
|----------------|---------------------------------------------------------|----------------------------------|
| **Organization** | `OrganizationSetting`s | Slug unique globally; settings keys are tenant-scoped. |
| **Branch** | `Zone`s, `OperatingHours` | Branch code unique within organization; zones unique within branch. |
| **User** | (single root) | Email/username unique per organization; role membership consistent with assigned branches. |
| **Role** | role↔permission links | Permission codes are valid; role code unique per organization. |
| **Session** | (single root) | Refresh token rotation; revoked sessions cannot be reused. |
| **Customer** | `CustomerConsent`, `FaceEmbeddingRef` (registration only) | Cannot hold biometric reference without an active consent record. |
| **Employee** | `EmploymentRecord` | Employee code unique per organization; one employee maps to at most one user. |
| **Camera** | `CameraHealthState`, `CameraAIConfig` | Camera code unique per organization; AI config references valid `PipelineKind`s. |
| **Category** | (self-referential tree) | No cycles; slug unique per organization. |
| **Product** | `ProductMedia` | SKU unique per organization; price has non-negative amount. |
| **InventoryItem** | `StockMovement`s | `quantity ≥ 0`; `reservedQuantity ≤ quantity`; movements form a consistent history. |
| **Stocktake** | counted-line entries | Posting variances generates `StockMovement`s atomically. |
| **ShoppingCart** | `CartLine`s | Cart total = sum of lines; reservations on inventory mirror lines; status transitions are legal. |
| **Order** | `OrderLine`s, `Payment`s, `Refund`s | Total = sum of lines − refunds; status transitions are legal; once `PAID`, lines and totals are immutable. |
| **VisionPipeline** | active `ModelRegistration` | Active model is compatible with the pipeline kind; one active version at a time. |
| **Track** | trail of `DetectionEvent`s | Detections are append-only; track ID is unique within a camera-time window. |
| **Notification** | `DeliveryAttempt`s | Final status is one of SENT/FAILED/READ; preferences honoured. |
| **Subscription** | (single root) | URL is unique per organization; HMAC secret is rotated atomically. |
| **Report** | `ReportRun`s, `ScheduledReport`s | Parameters validated against the template before run. |
| **AuditLog** | (immutable) | Append-only; once written, never updated. |

#### Aggregate sizing rules

- An aggregate **MUST** be loadable and savable in a single transaction.
- Long lists that grow unbounded (e.g. all `StockMovement`s for a product)
  **MUST NOT** be loaded as a navigable collection on the root; they are
  queried by ID through a repository.
- Cross-aggregate consistency is **eventual** and achieved via domain
  events.

---

# Domain Events

> **Naming convention:** `<Subject><Verb-Past-Tense>` in PascalCase, scoped
> by producing context. The event **describes a fact about the past**;
> handlers may not refuse it.
>
> Every event carries: `eventId`, `eventName`, `eventVersion`,
> `occurredAt`, `organizationId`, `branchId` (when applicable),
> `aggregateId`, and a typed payload.

### Identity & Access

- `UserRegistered`
- `UserActivated`
- `UserLoggedIn`
- `UserLoggedOut`
- `UserLoginFailed`
- `PasswordResetRequested`
- `PasswordChanged`
- `RoleAssignedToUser`
- `RoleRevokedFromUser`
- `PermissionDenied` *(audit-grade event)*

### Organization & Branch

- `OrganizationCreated`
- `OrganizationSettingChanged`
- `BranchOpened`
- `BranchDeactivated`
- `ZoneConfigured`

### Customer

- `CustomerRegistered`
- `CustomerProfileUpdated`
- `CustomerConsentGranted`
- `CustomerConsentWithdrawn`
- `CustomerMerged`
- `CustomerSegmentChanged`

### Employee

- `EmployeeHired`
- `EmployeeTerminated`
- `EmployeeLinkedToUser`

### Catalog

- `ProductCreated`
- `ProductUpdated`
- `ProductPriceChanged`
- `ProductDiscontinued`
- `CategoryCreated`
- `CategoryReorganized`

### Inventory

- `InventoryUpdated`
- `StockReserved`
- `StockReleased`
- `StockCommitted`
- `StockAdjusted`
- `StockTransferred`
- `LowStockDetected`
- `StocktakePosted`

### Cart & Order

- `CartOpened`
- `ItemAddedToCart`
- `ItemRemovedFromCart`
- `CartAbandoned`
- `CartConverted`
- `OrderPlaced`
- `OrderPaid` *(equivalent name: `PaymentCompleted`)*
- `OrderCancelled`
- `OrderRefunded`
- `PaymentFailed`
- `ReceiptIssued`

### Camera

- `CameraRegistered`
- `CameraCameOnline`
- `CameraWentOffline`
- `CameraAIConfigChanged`

### AI Processing

- `CustomerDetected`
- `ShopperEnteredBranch`
- `ShopperLeftBranch`
- `ProductDetected`
- `ProductPickedUp`
- `ProductPutBack`
- `ProductRecognized`
- `TrackStarted`
- `TrackEnded`
- `TheftDetected`
- `QueueDetected`
- `QueueLengthExceededThreshold`
- `HeatmapUpdated`
- `ShelfBecameEmpty`
- `ShelfRestocked`
- `ModelDeployed`

### Notification

- `NotificationCreated`
- `NotificationSent`
- `NotificationFailed`
- `NotificationRead`
- `WebhookDeliveryFailed`

### Analytics & Reporting

- `FootfallAggregateUpdated`
- `ConversionAggregateUpdated`
- `DailyReportGenerated`
- `ScheduledReportDelivered`

### Audit (cross-cutting)

- `AuditEntryRecorded`

---

# Event Flows

### Flow A — AI-assisted smart cart (the headline scenario)

```
[Camera]
   └─ frame ─►
[AI Processing]
   ├─ TrackStarted (shopper)
   ├─ ProductDetected → ProductRecognized
   └─ emits ProductPickedUp
            │
            ▼
[Order & Cart]                     [Inventory]
  ├─ opens/uses ShoppingCart        │
  ├─ adds CartLine                  │
  ├─ emits ItemAddedToCart  ───────►├─ reserves stock
                                    └─ emits StockReserved

[Customer]  (shopper proceeds to checkout, pays)
[Order & Cart]
   ├─ converts cart to Order
   ├─ emits OrderPlaced
   ├─ payment settled
   └─ emits OrderPaid ────────────► [Inventory]   commits reservation → StockCommitted
                                  ► [Notification] receipt sent
                                  ► [Analytics]   conversion/revenue updated
                                  ► [Audit]       AuditEntryRecorded
```

### Flow B — Out-of-stock detection on the shop floor

```
[AI Processing]
   └─ emits ShelfBecameEmpty
            │
            ▼
[Inventory]                        [Notification]
   ├─ raises LowStockDetected ─────► creates Notification
                                     ├─ honours NotificationPreference
                                     └─ emits NotificationSent
[Analytics]   counts shelf-empty duration per branch/zone
```

### Flow C — Loss prevention

```
[AI Processing]
   └─ emits TheftDetected (with TrackId, FrameRefs, Confidence)
            │
            ▼
[Notification]                     [Audit]
   ├─ pushes CRITICAL alert         └─ records AuditEntryRecorded
   ├─ ignores quiet hours
   └─ emits NotificationSent
[Analytics]
   └─ adds to shrinkage indicator
```

### Flow D — Queue SLA breach

```
[AI Processing]
   └─ emits QueueDetected (length, waitEstimate)
            │
            ▼ (when threshold exceeded)
   └─ emits QueueLengthExceededThreshold
            │
            ▼
[Notification] ─► duty manager
[Analytics]   ─► queue history aggregate
```

### Flow E — Customer recognition (consent-gated)

```
[AI Processing]
   ├─ matches face embedding (only on consented customers)
   └─ emits CustomerDetected (CustomerId)
            │
            ▼
[Customer]
   └─ updates last-seen
[Order & Cart]
   └─ may pre-fill the active cart with the recognised customer
[Analytics]
   └─ frequency segment update
```

### Producer / Consumer Matrix (summary)

| Event | Producer | Primary Consumers |
|-------|----------|-------------------|
| `CustomerDetected` | AI Processing | Customer, Order & Cart, Analytics |
| `ProductDetected` | AI Processing | (debug / analytics; rarely consumed) |
| `ProductPickedUp` / `ProductPutBack` | AI Processing | Order & Cart |
| `ProductRecognized` | AI Processing | Order & Cart |
| `ItemAddedToCart` / `ItemRemovedFromCart` | Order & Cart | Inventory, Notification |
| `OrderPlaced` | Order & Cart | Inventory, Analytics |
| `OrderPaid` *(= PaymentCompleted)* | Order & Cart | Inventory, Notification, Analytics, Audit |
| `OrderRefunded` | Order & Cart | Inventory, Analytics, Audit |
| `InventoryUpdated` | Inventory | Notification, Analytics |
| `LowStockDetected` | Inventory | Notification |
| `ShelfBecameEmpty` / `ShelfRestocked` | AI Processing | Inventory, Analytics |
| `TheftDetected` | AI Processing | Notification, Audit, Analytics |
| `QueueDetected` / `QueueLengthExceededThreshold` | AI Processing | Notification, Analytics |
| `HeatmapUpdated` | AI Processing | Analytics |
| `CameraWentOffline` | Camera | Notification, AI Processing |
| `NotificationSent` | Notification | Audit |

### Event versioning

- Every event has an explicit `eventVersion` (`v1`, `v2`, …).
- Producers **MAY** publish multiple versions in parallel during migration
  windows.
- Consumers **MUST** declare the versions they understand and ignore
  unknown versions safely.
- An event's name and payload shape are part of the **public contract** of
  the producing context; breaking changes require a new event name or a
  new version, never a silent mutation.

### Idempotency

- Every event is **idempotent on `eventId`** at the consumer side. A
  consumer that receives the same `eventId` twice **MUST** produce the
  same observable effect as receiving it once.

---

# Context Relationships

The dependency model uses DDD context-map terms:
**U** (Upstream) → **D** (Downstream); **CF** = Conformist;
**ACL** = Anti-Corruption Layer; **OHS** = Open Host Service;
**PL** = Published Language (domain events).

### Hard rules

- A **D** context depends on the published language of its **U** context
  but **MUST NOT** reach into U's storage or internal state.
- Any external system (payment gateway, MQTT device, third-party CRM) is
  consumed through an **Anti-Corruption Layer**; external concepts do not
  leak into the domain.
- The **domain events** of each context are the **Published Language**;
  consumers depend on the event schema only.

### Inbound / Outbound matrix

| Context | Depends on (consumes from) | Publishes for |
|---------|-----------------------------|----------------|
| **Identity & Access** | Organization (for tenancy), Employee (linking) | Every other context (auth context, permissions) |
| **Organization** | — | Every other context |
| **Branch Management** | Organization | Every other context |
| **Product Catalog** | Organization | Inventory, Order & Cart, AI Processing, Analytics, Reporting |
| **Inventory** | Product Catalog, Branch Management | Order & Cart (reservations), Notification, Analytics, Reporting |
| **Order & Cart** | Product Catalog, Inventory (ACL on reservations), Customer (snapshot), Employee (cashier snapshot) | Analytics, Notification, Audit, Reporting |
| **Customer** | Organization, AI Processing (recognition results, consent-gated) | Order & Cart, Analytics, Notification |
| **Employee** | Organization, Branch Management, Identity & Access (link) | Order & Cart (cashier), Analytics |
| **Camera** | Organization, Branch Management | AI Processing, Notification |
| **AI Processing** | Camera, Product Catalog (model-time snapshot), Customer (consent for recognition) | Order & Cart, Inventory, Customer, Notification, Analytics, Audit |
| **Event & Notification** | Every event-producing context | Audit |
| **Analytics** | Almost every producing context | Reporting, Dashboard surface |
| **Reporting** | Analytics, Order & Cart, Inventory | Notification (delivery), Audit |

### Contexts that **MUST NEVER** directly access each other

- **Frontend** ⟶ any **infrastructure** of any context. *(The frontend talks
  only to the API gateway of the backend.)*
- **AI Processing** ⟶ **Inventory** / **Order & Cart** / **Customer**
  databases. *(AI emits events; backend contexts decide what to persist.)*
- **Order & Cart** ⟶ **Inventory** internal tables. *(It calls the Inventory
  application service or reacts to its events.)*
- **Any context** ⟶ another context's `domain/` or `infrastructure/`
  packages.
- **Analytics / Reporting** ⟶ the *write* side of any other context.
  Analytics is strictly **read-and-aggregate**.

### Approved upstream/downstream pairs (selected)

| Upstream (U) | Downstream (D) | Pattern |
|--------------|----------------|---------|
| AI Processing | Order & Cart | PL (event-driven) |
| AI Processing | Inventory (shelf events) | PL (event-driven) |
| Inventory | Order & Cart | OHS (application service) + PL (`StockReserved`, etc.) |
| Product Catalog | Inventory, Order & Cart | OHS (read), PL on changes |
| Customer | Order & Cart, Analytics | PL |
| Camera | AI Processing | OHS (registration), PL (lifecycle) |
| External payment gateway | Order & Cart | ACL inside Order & Cart |
| External MQTT devices | (future) Camera / Inventory | ACL at the bridge |

---

# Business Rules

> Global, cross-context invariants. Every implementation **MUST** preserve
> them.

### Multi-tenant & multi-branch isolation

- **BR-1.** Every business aggregate **MUST** belong to exactly one
  Organization.
- **BR-2.** Every operationally-scoped aggregate (Cart, Order, Inventory,
  Camera, Employee, Notification target) **MUST** identify its Branch.
- **BR-3.** No query, report, or AI event **MAY** expose data from another
  Organization. This is a hard isolation boundary, not a soft filter.
- **BR-4.** A user assigned to a subset of branches **MUST** be invisible
  to and from branches outside that set.
- **BR-5.** Aggregating across Branches is allowed only for users with
  organization-wide scope.

### Catalog & pricing

- **BR-6.** A Product's SKU is **immutable** once any inventory or sale
  references it; a renamed SKU is a new product.
- **BR-7.** Prices are always represented as `Money` (amount + currency);
  arithmetic across different currencies **MUST** be refused at the
  domain layer.
- **BR-8.** Discontinued products **MUST NOT** be added to new carts but
  **MUST** remain visible in historical orders and reports.

### Inventory consistency

- **BR-9.** `quantity` and `reservedQuantity` of an `InventoryItem` are
  **non-negative**. The domain refuses transitions that would break this.
- **BR-10.** Adding a line to a cart reserves stock; removing or
  abandoning a cart releases it; paying the order commits the reservation
  in **one atomic transaction**.
- **BR-11.** Negative stock is allowed only when the tenant's setting
  `inventory.allow_negative` is explicitly on; otherwise it is refused.
- **BR-12.** Every change to `quantity` **MUST** be paired with a
  `StockMovement` carrying a `MovementReason`. There is no silent
  inventory change.
- **BR-13.** Inter-branch transfers are two `StockMovement`s
  (`TRANSFER_OUT` + `TRANSFER_IN`) bound by a single transfer reference.

### Cart synchronization

- **BR-14.** A Cart belongs to exactly one Branch and (optionally) one
  Customer. Items in the cart **MUST** be available at that Branch.
- **BR-15.** Carts have a configured TTL. Expired carts transition to
  `ABANDONED` and release their reservations.
- **BR-16.** AI-sourced cart updates (`AI_VISION`) **MUST** be reconciled
  with manual cashier actions; the cashier's action wins on conflict.
- **BR-17.** Converting a Cart to an Order is a single transaction; the
  Cart's status becomes `CONVERTED` and the Order's `OrderLine`s are
  copied from the Cart's `CartLine`s. No mutation thereafter.

### Order & payment

- **BR-18.** An Order's totals **MUST** equal the sum of its lines minus
  refunds. The domain refuses any update that would break this.
- **BR-19.** Once an Order's status is `PAID`, lines, prices, and totals
  are immutable. Corrections are issued as Refunds.
- **BR-20.** Refunds **MUST** restore stock atomically with the refund
  record.
- **BR-21.** Every mutating payment operation **MUST** be idempotent on a
  payment-intent identifier.

### Customer & privacy

- **BR-22.** No biometric processing (face recognition, embedding) may
  occur for a customer without an **active** `CustomerConsent` for
  `FACE_RECOGNITION`.
- **BR-23.** Withdrawing consent **MUST** delete the corresponding
  embeddings within the documented privacy SLA.
- **BR-24.** Anonymous shopper tracking is permitted and does not require
  consent, **provided** it does not produce or retain personally
  identifying signals.

### AI detection confidence

- **BR-25.** Every AI output carries a `Confidence` value. Downstream
  domains **MUST NOT** treat a recognition as authoritative below the
  context's documented threshold.
- **BR-26.** Per-pipeline thresholds:
  - `ProductRecognized` **MUST** meet `confidence ≥ 0.85` before
    auto-adding to a cart. Lower confidences route to the human-review
    queue.
  - `CustomerDetected` (face) **MUST** meet `confidence ≥ 0.90`.
  - `TheftDetected` **MUST** meet `confidence ≥ 0.80` **and** corroborate
    with at least one supporting signal (e.g. `ProductPickedUp` without a
    matching `ItemAddedToCart` or a paid `OrderLine`).
- **BR-27.** Thresholds are configurable per tenant **above** the
  platform's documented floor; they may not be lowered below it.
- **BR-28.** AI events are **never** allowed to bypass the application
  layer of consumer contexts. AI may *propose*; the domain *decides*.

### Real-time update rules

- **BR-29.** Real-time UI updates **MUST** be pushed via WebSocket, not by
  client polling.
- **BR-30.** Real-time topics are scoped by Organization (and Branch
  where applicable) and **MUST** be permission-checked on subscription.
- **BR-31.** A lost WebSocket message **MUST NOT** corrupt domain state;
  domain state is owned by Postgres, the WebSocket is informational.
- **BR-32.** End-to-end latency from event emission to client delivery
  **SHOULD** be ≤ 500 ms inside a single deployment.

### Audit & traceability

- **BR-33.** Every domain event **MUST** be recordable to the Audit
  context with the original `eventId`, producer, and payload.
- **BR-34.** Security-relevant events (`PermissionDenied`,
  `RoleAssignedToUser`, `CustomerConsentWithdrawn`, `OrderRefunded`,
  `TheftDetected`) **MUST** be auditable and **MUST NOT** be deletable.

---

# Future Extensions

Tracked as **planned domain growth**. Each item below requires its own
context map update and (where it introduces new aggregates or events)
amendments to this document. Items are listed in no particular order.

### Sales & Commerce

- **Promotions & Loyalty Context** — campaigns, points, tiers; producer
  of `LoyaltyPointsEarned`, `PromotionApplied`.
- **Self-Checkout Context** — formalises the kiosk surface and its
  reconciliation rules with AI-assisted carts.
- **B2B / Wholesale orders** — long-running orders with credit terms.

### Vision & AI

- **Cross-camera Re-identification** as its own context, separate from
  in-store tracking, with a dedicated consent model.
- **Behavioural analytics** — group composition, family detection,
  product-interaction events (`ProductInspected`, `ProductTried`).
- **Active learning** — a context that turns human review queues into
  training labels and model retraining runs.

### Operations

- **Task & Workforce Context** — assignable tasks (restock, clean, open,
  close) with SLAs.
- **Maintenance Context** — camera and hardware maintenance schedules.
- **Energy / Environment Context** — environmental sensors via MQTT.

### Customer & Marketing

- **Marketing Automation Context** — segment-driven campaigns reacting to
  `CustomerSegmentChanged`.
- **Personalised in-store experience** — signage / app reactions to
  `CustomerDetected`.

### Platform-level

- **Billing & Subscription Context** — for SaaS deployments (per-tenant
  plans, usage metering).
- **Marketplace of AI modules** — optional pipelines a tenant can opt into
  with explicit consent and pricing.
- **Public API / Developer Context** — third-party app registrations and
  OAuth scopes.
- **Long-term archive** — cold storage for old detections, clips, and
  aggregates with a retention policy domain.

### Anti-goals (deliberately not modelled)

- A built-in eCommerce storefront (separate product, not VisionMart).
- Stand-alone payroll or HR (Employee is intentionally a thin operational
  record).
- Stand-alone WMS (warehouse management); Inventory is store-level only.

---

*This document is the canonical domain model. Any change to entities,
aggregates, events, or business rules requires a PR that updates **only
this file** (and, when needed, an ADR explaining the rationale).*
