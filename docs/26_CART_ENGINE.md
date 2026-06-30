# VisionMart — Smart Cart, Checkout Engine & Inventory Sync

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/26_CART_ENGINE.md`
> **Owner:** Lead Retail System Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** system **design** only. No code, no APIs, no DDL, no
> framework-specific instructions. Where this document conflicts with
> implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract](ARCHITECTURE_CONTRACT.md) ·
> [Domain Model — Order & Cart](DOMAIN_MODEL.md) ·
> [System Design — Data Flows](SYSTEM_DESIGN.md) ·
> [AI Overview](20_AI_OVERVIEW.md) ·
> [Camera Manager](21_CAMERA_MANAGER.md) ·
> [Authentication](13_AUTHENTICATION.md) ·
> [Notification Center](15_NOTIFICATION_CENTER.md) ·
> [WebSocket](16_WEBSOCKET.md)

---

# Smart Cart Overview

The Smart Cart is the **bridge** between AI perception and retail
transactions. It turns AI proposals like *"Customer 123 picked up
product 456"* into authoritative backend state — a `ShoppingCart`,
its `CartLine`s, and (when checkout completes) an `Order`. It also
keeps inventory consistent with those interactions in real time.

The Smart Cart respects the cardinal rule of the platform
([AI Overview](20_AI_OVERVIEW.md#ai-system-overview)):

> **AI proposes; backend decides.** Cart updates and inventory
> reservations are decisions made by the **Cart Engine** inside the
> backend; the AI Engine never writes to these tables.

### What is a Smart Cart in VisionMart?

- A **`ShoppingCart` aggregate** in the Sales context that is:
  - Either **AI-driven** (built from AI events emitted by the camera
    pipeline), or
  - **POS-driven** (built from a cashier scanning at a register), or
  - **Hybrid** (AI-suggested, cashier-confirmed).
- It is always **branch-scoped** (`branch_id` is `NOT NULL`).
- It is **anonymous-by-default**; a `customer_id` is attached only
  when consented recognition (or explicit customer identification)
  succeeds.

### Physical cart vs AI cart

| Aspect | Physical cart (POS) | AI cart (Smart Cart) |
|--------|---------------------|----------------------|
| Source of truth | Cashier scans | AI events (pick / return) + optional cashier confirmation |
| Visibility | Cashier screen | Live dashboard + customer mobile UI (future) |
| Membership trigger | Scan barcode | `ProductPickedUp` rule (AI) or hybrid confirmation |
| Confidence | 1.0 | Per-event confidence from the rule engine |
| Latency target | n/a | ≤ 1 s end-to-end (camera → cart UI) |
| Authoritative state | Postgres | Postgres (Redis mirror) |

Both kinds of cart share the **same** `ShoppingCart` aggregate. The
`source` field distinguishes them and the `added_via` field on each
`CartLine` records whether the line was added by `manual` (cashier),
`ai` (smart cart), or `hybrid` (AI-suggested, cashier-confirmed).

### Customer-cart association model

- A cart **MAY** be linked to a `customer_id` via:
  - **Consented face recognition** (the AI Engine attaches a
    customer_id to a `TrackingSession`; the Cart Engine carries that
    onto the cart).
  - **Explicit identification** (cashier scans a loyalty code or
    customer signs in on a mobile app).
- A cart that never gets a `customer_id` is **anonymous** and that is
  perfectly normal.
- A cart **MUST NEVER** be implicitly shared between two customers;
  per BR-15 the merge of two carts is an explicit, audited operation.

### Session-based lifecycle (conceptual)

- An AI-driven cart is opened on the **first credible AI proposal**
  for a tracked shopper in a branch and is closed when the shopper
  leaves, pays, or the session times out.
- A cart's lifetime is bounded by `expires_at`; an idle cart is
  cleaned up by a background sweeper (BR-13).

---

# Cart Lifecycle

> **Cardinal rule:** every state transition below is **driven by the
> Cart Engine** (backend). The AI Engine never moves a cart directly;
> it only emits events the Cart Engine subscribes to.

### Stage diagram (canonical)

```
[AI: CustomerDetected]  ─or─  [POS: CashierStartsTransaction]
        │                              │
        ▼                              ▼
                  ┌──────────────────────────┐
                  │      CartCreated         │ status = OPEN
                  └─────────────┬────────────┘
                                │
   [AI: ProductPickedUp]        │     [POS: ItemScanned]
   [AI: ProductRecognized]      │     [Hybrid: ItemConfirmed]
                                ▼
                  ┌──────────────────────────┐
                  │       ItemAdded          │ → CartUpdated
                  └─────────────┬────────────┘
                                │
   [AI: ProductReturned]        │     [POS: ItemVoided]
                                ▼
                  ┌──────────────────────────┐
                  │      ItemRemoved         │ → CartUpdated
                  └─────────────┬────────────┘
                                │
                                │  (Customer reaches checkout)
                                ▼
                  ┌──────────────────────────┐
                  │   CheckoutInitiated      │ status = PENDING_PAYMENT
                  └─────────────┬────────────┘
                                │
        ┌───── payment failed ──┴─── payment ok ──────┐
        ▼                                              ▼
┌──────────────────┐                       ┌──────────────────┐
│     OPEN         │ (back to OPEN with    │   OrderCreated   │
│ (retry or void)  │  validation message)  └────────┬─────────┘
└──────────────────┘                                │
                                                    ▼
                                       ┌──────────────────────┐
                                       │     CartClosed       │ status = CONVERTED
                                       └──────────────────────┘
```

Other terminal states:

- **`ABANDONED`** — sweeper closed an idle cart past `expires_at`
  (BR-13).
- **`CANCELLED`** — operator-initiated cancellation; audited.

### Stage explanations

- **CustomerDetected / Cashier starts.** The first credible trigger
  for a cart. AI source is *recognition or anonymous-track entry into
  a "checkout candidate" zone*. POS source is a cashier opening a new
  transaction.
- **CartCreated.** The Cart Engine creates a `ShoppingCart` row in
  status `OPEN`, with `branch_id`, optional `customer_id`,
  `session_id`, `source`, `expires_at`. Emits `CartCreated`.
- **ItemAdded.** A `CartLine` is inserted (or quantity incremented)
  inside the cart aggregate; totals are recomputed; an inventory
  reservation is taken. Emits `CartUpdated`.
- **ItemRemoved.** A `CartLine` quantity is decremented or removed;
  totals recomputed; the reservation is released. Emits
  `CartUpdated`.
- **CheckoutInitiated.** The Cart Engine validates the cart, freezes
  its totals, transitions to `PENDING_PAYMENT`, and asks the Payment
  Engine to capture funds. Emits `CheckoutInitiated`.
- **OrderCreated.** On successful payment, the Order Engine clones
  the cart's lines into an `Order` aggregate, commits the inventory
  movement, and marks the source cart `CONVERTED`. Emits
  `OrderCreated` and `InventoryUpdated`.
- **CartClosed.** Terminal state. The cart is immutable from here.

---

# Real-time Synchronization

### Goals

- A change made by AI in a branch is visible on the dashboard and
  any cashier UI **within 1 second** (p95).
- Multiple viewers (cashier station + branch dashboard + customer
  mobile in the future) see the **same** cart state.
- A subscriber that briefly disconnects can **catch up** without
  losing or double-counting events.

### Update flow

```
[Cart Engine — write path]
        │ 1. Postgres transaction commits cart change
        │ 2. Redis mirror refreshed (cart hash by id)
        │ 3. Domain event published on the EventBus
        ▼
[WebSocket Gateway]
        │ Pub/Sub fan-out on the topic
        │ `org.{orgId}.branch.{branchId}.cart.{cartId}`
        ▼
[Subscribers]
        - Cashier UI
        - Branch dashboard
        - Customer companion app (future)
```

### Redis usage for active cart state

- Each open cart has a Redis hash keyed by `cart:{branchId}:{cartId}`
  with the lines and totals — used by **hot reads** in the UI and by
  the AI rule engine for proximity decisions.
- The Postgres row is **authoritative**. Redis is a **mirror**
  refreshed inside the same write path. Loss of the Redis key only
  degrades latency, never correctness.
- The mirror carries a `version` (monotonic counter) so clients can
  detect stale reads.

### WebSocket usage

- Subscribers attach to the cart topic at view time; each `subscribe`
  is permission-checked
  ([Authentication §Authorization Flow](13_AUTHENTICATION.md#authorization-flow)).
- Updates are **idempotent** on `event_id`; clients track a
  monotonic offset per topic and request a small backfill on
  reconnect.
- WebSocket payloads carry the **minimum** state to render — full
  cart detail is fetched on demand.

### Conflict resolution

- **Single-writer principle.** All cart mutations go through the
  Cart Engine. AI does not write; cashiers write via the Cart Engine
  too (the POS UI calls Cart Engine endpoints).
- **Optimistic concurrency** on cart updates — every write carries
  the expected `version`. Stale writes are rejected with a domain
  error and the caller retries with the latest state.
- **AI-vs-cashier conflicts.** A cashier action wins over an AI
  proposal when they contradict (e.g. cashier removes a line that AI
  proposes to re-add). The AI Engine treats subsequent proposals as
  new candidates; the rule engine's cooldown prevents thrashing.

---

# AI → Cart Mapping Logic

### Mapping table

| AI event | Cart action | Conditions / notes |
|----------|-------------|--------------------|
| `ProductPickedUp` (with `ProductRecognized`) | **AddItemToCart** (qty +1) | Recognition confidence ≥ 0.85 + stability ≥ 3 frames (BR-26). Customer/track must be associated with an open cart. |
| `ProductPickedUp` (no recognition) | **Suggest** (insert as `added_via='ai_pending'`) | Held for cashier confirmation. Does NOT reserve inventory until confirmed. |
| `ProductReturned` | **RemoveItemFromCart** (qty -1) | Must match a line previously added in this cart by AI; otherwise emits `AIReturnUnknown` for review. |
| `ProductSwapped` | **RemoveItem(old)** + **Suggest(new)** | Swap is a low-confidence cue; the new SKU enters as a suggestion. |
| `ProductHeldTooLong` | **Hint** | Informational; raises operator hint, does NOT mutate cart. |
| `CustomerLostTracking` (track ended without checkout) | Start cart timeout | After grace window, cart enters `ABANDONED` (sweeper). |
| `CustomerReacquired` (re-ID) | Re-attach cart | Only if AI proposes with sufficient confidence; otherwise a new cart begins. |
| `TheftSuspected` / `TheftDetected` | **Lock cart** for review | Cart cannot be checked out until released by a manager; audited. |
| `CartSplit` (multiple shoppers share basket) | **Manual review** | Cart engine flags the cart; no automatic split in v1. |

### Mapping rules

- **Confidence first.** No AI event below the rule-stage threshold
  ever affects authoritative cart state (BR-26).
- **Ownership check.** The Cart Engine resolves
  `(camera_id, tracking_session_id, customer_id?)` to a *single*
  open cart in the same branch. If multiple candidates exist, the
  event is held and a `CartAssociationAmbiguous` is raised.
- **Idempotency.** Every AI event carries `event_id`; the Cart
  Engine refuses to apply the same event twice.
- **Schema versioning.** AI events are versioned (`@vN`); the Cart
  Engine accepts known versions and rejects unknown ones with an
  audit entry.
- **Backend always validates.** Even with a perfect recognition, the
  Cart Engine re-checks:
  - The product exists, is active, has a unit price.
  - The branch sells the product (planogram / branch catalogue).
  - The cart is `OPEN` and not locked.
  - The inventory can be reserved (or the line is suggested-only).

---

# Checkout Engine

### Cart validation rules (pre-checkout)

- Cart is in `OPEN` state, not locked, not expired.
- All lines reference active products.
- All quantities ≥ 1; line totals match `unit_price * qty -
  discount`.
- For AI-suggested lines, each has been confirmed (or rejected) —
  no `ai_pending` lines may proceed to checkout.
- All inventory reservations are still valid; if any has been
  released, the line is **re-evaluated** against current stock.
- The cart total is recomputed from scratch and compared to the
  stored total; mismatch aborts checkout with a domain error.

### Price calculation strategy

- **Authoritative prices come from the catalogue** at *checkout
  time*. The price snapshot at add-time is shown for transparency,
  but the checkout total uses the **current price** unless a
  documented price-lock period applies.
- **Branch-level pricing (future-ready).** Pricing is layered so a
  branch override can be added without rewriting the engine
  (`base_price → branch_override → promotion`).
- **Currency** is per organization (or per branch when configured);
  conversion is **not** performed by the cart at checkout in v1.

### Discount / promotion hooks (future-ready)

- The checkout pipeline exposes a **pluggable promotions step**
  (cart-level, line-level, customer-level). v1 ships with **no
  active promotion plugins**; the seam exists so the v1.x roadmap can
  add promotions without changing the engine surface.
- Promotion outcomes are recorded per line (`discount_amount`,
  `discount_reason`) for audit and reporting.

### Payment simulation layer

- v1 ships a **payment simulation** that always succeeds (or fails
  on demand for testing). The interface is the same that a real
  gateway will implement, so the swap is configuration-only.
- The payment step:
  1. Receives a freeze of the cart total (`amount`, `currency`).
  2. Requires an **idempotency key** so retries don't double-charge
     (BR-17).
  3. Returns `PaymentCaptured` (success) or `PaymentFailed`
     (with reason).
- The cart **does not** transition to `CONVERTED` until
  `PaymentCaptured` returns successfully.

### Order generation flow

```
[CheckoutInitiated]
        │ freeze totals, validate cart
        ▼
[PaymentRequested] ── Payment Engine ── [PaymentCaptured | PaymentFailed]
        │ on captured:
        ▼
[Order Engine]
        │ 1. open transaction
        │ 2. create Order from cart snapshot
        │ 3. copy CartLine → OrderLine (immutable)
        │ 4. write Payment row
        │ 5. commit inventory movements
        │ 6. mark cart CONVERTED, set converted_at
        │ 7. commit transaction
        ▼
[OrderCreated] (event)
[InventoryUpdated] (event)
[NotificationSent] (receipt — future)
```

All of steps 1–7 happen in **one Postgres transaction** so the cart,
order, payment, and inventory movements are committed atomically. A
failure at any step rolls the whole thing back; reservations remain
in place for the next attempt.

---

# Inventory Sync

### Two-step reservation model

- **Soft hold (reservation).** When a line is added to a cart, the
  Cart Engine increments the line's product/branch
  `reserved_quantity` and decrements *available* (which is computed
  as `quantity - reserved_quantity`). No `StockMovement` row is
  written yet.
- **Hard deduction (commit).** When the order is paid, the
  reservation is *consumed*: `quantity` is decremented and
  `reserved_quantity` is decremented by the same amount; a
  `StockMovement` row is written with `reason = SALE` and a
  reference to the `Order`.
- **Release.** When a line is removed or a cart is abandoned /
  cancelled, the reservation is released — `reserved_quantity` is
  decremented; **no** `StockMovement` row is written for releases.

### Oversell prevention

- Reservation increments happen **inside the cart write
  transaction** with a row-level lock on the `InventoryItem` row
  (Postgres `FOR UPDATE`); two concurrent carts cannot both reserve
  the last unit.
- A reservation that would push `reserved_quantity > quantity` is
  rejected with a domain error `InsufficientStock`.
- Inventory invariants (BR-9) are enforced by domain logic plus a
  database `CHECK` (`quantity >= 0`, `reserved_quantity >= 0`,
  `reserved_quantity <= quantity`).

### Soft stock vs hard stock

| Scenario | Soft (reservation) | Hard (commit) |
|----------|--------------------|---------------|
| Add line to AI cart | ✅ | — |
| Add line to POS cart | ✅ | — |
| Cashier confirms an AI suggestion | ✅ | — |
| Payment captured | release the line's reservation, write `StockMovement(SALE)` | ✅ |
| Cart abandoned / cancelled | release reservation | — |
| Operator manual adjustment | — | ✅ (`StockMovement(ADJUSTMENT)`) |
| Stocktake variance | — | ✅ (`StockMovement(ADJUSTMENT)` with stocktake ref) |

### Real-time stock updates

- After every commit affecting inventory, the Cart Engine publishes
  `InventoryReserved`, `InventoryReleased`, or `InventoryCommitted`
  domain events.
- The dashboard subscribes to per-branch inventory topics; gauges
  update via WebSocket within the platform's real-time latency
  target.
- Inventory snapshots for the AI rule engine (e.g. "is this product
  still in stock?") are read from a **Redis cache** that is refreshed
  on each inventory event; Postgres remains authoritative.

### Conflict handling

- Two simultaneous cart adds racing for the last unit are serialised
  by the row lock; the **loser** receives `InsufficientStock` and
  the affected cart shows a remediation hint.
- A late-arriving AI event whose reservation cannot be satisfied is
  recorded as `AIProposalDeclined(InsufficientStock)` and surfaced
  to operations.

---

# Data Consistency

### Strong consistency boundaries

- **Within the cart aggregate.** Lines, totals, status, and the cart-
  side inventory reservation all change in **one** Postgres
  transaction.
- **Within the order aggregate at checkout.** Order, OrderLines,
  Payment row, `StockMovement` rows, and the cart's transition to
  `CONVERTED` are committed in **one** transaction.
- **Audit.** Sensitive transitions (cart lock, manual override,
  refund) write an `AuditLog` row inside the same transaction.

### Eventual consistency boundaries

- **Cross-context fan-out.** The Notification Center, Analytics, and
  the dashboard's WebSocket gateway receive **domain events** and
  catch up asynchronously (typically sub-second).
- **Redis mirrors.** Cart and inventory Redis mirrors trail Postgres
  by milliseconds; clients prefer Redis for hot reads and fall back
  to Postgres if the mirror is stale or missing.

### AI event delays

- AI events carry `occurred_at` (frame capture time) and arrive at
  the Cart Engine with bounded but variable latency.
- The Cart Engine compares `occurred_at` to the latest cart
  modification: an event whose `occurred_at` is **older than the
  last cart modification by more than a configured skew** is **either
  ignored or downgraded to a suggestion**, never applied silently.
- Out-of-order events are tolerated because each event is
  idempotent on `event_id` and the cart's authoritative state is
  the single source of truth.

### Duplicate event prevention

- The Cart Engine maintains a small **dedupe cache** of recently-
  applied `event_id`s per cart. A duplicate is a no-op.
- `ProductPickedUp` events for the same `(track_id, product_id)` in
  the rule engine's cooldown window are dropped at the AI Engine
  itself (AI Overview §Event Deduplication); this is defence in
  depth.

---

# Cart State Management

### Active cart storage strategy

- **Redis** (`cart:{branchId}:{cartId}` hash + per-branch index
  `cart:branch:{branchId}:open`) holds the **mirror** of every open
  cart for the branch — used by AI proximity logic and dashboard hot
  reads.
- **Bounded TTL** equal to the cart's `expires_at` plus a small
  grace period.
- Loss of Redis triggers a backfill from Postgres on next read.

### Persistent cart storage

- **Postgres** holds the canonical `ShoppingCart` and `CartLine`
  rows. All lifecycle transitions are persisted here first; Redis
  is updated only after a successful commit.
- Carts are **never hard-deleted** while their lines are reservation-
  holding; abandoned and cancelled carts are kept for analytics and
  cleaned up by lifecycle rules
  ([Database Design §Data Lifecycle](10_DATABASE_DESIGN.md#data-lifecycle)).

### Cart session timeout rules

- Each cart has `expires_at` (default 30 minutes from last
  modification; configurable per branch).
- A Celery Beat sweeper:
  - Finds carts with `expires_at < now()` and status `OPEN`.
  - Releases all reservations, marks the cart `ABANDONED`,
    publishes `CartAbandoned`.
- Activity (`ItemAdded`, `ItemRemoved`, AI proposal applied)
  **extends** `expires_at` so an active session doesn't get reaped.

### Multi-device tracking (future)

- A v2 customer companion app will allow the customer's phone to
  subscribe to their own cart's WebSocket topic and authoritative
  POS flows.
- The same `ShoppingCart` aggregate supports it; only the
  authentication audience and per-topic permissions differ.

---

# Edge Cases

| Case | Handling |
|------|----------|
| **Customer leaves without checkout** | Track ends; AI emits `TheftSuspected` (informational). The cart hits `expires_at` and is `ABANDONED` (reservations released). Analytics record an *unconverted session*; nothing financial happens. |
| **Camera loses tracking mid-session** | Cart remains `OPEN`. Subsequent recognition (re-ID or cashier scan) can re-attach the track to the cart. If no reacquisition happens before `expires_at`, cart is abandoned. |
| **Duplicate detection events** | Dedupe at AI Engine (cooldown) and at Cart Engine (recently-applied `event_id` cache). Duplicate at either layer is a no-op. |
| **Wrong product detected** | Recognition margin or planogram disagreement marks the line `ai_pending`. Cashier confirms or rejects. Persistent mistakes feed back into the model governance pipeline. |
| **Inventory mismatch (real shelf vs system)** | Stocktake variance posts `StockMovement(ADJUSTMENT)`; the system's view is corrected forward; historical movements are not rewritten (BR-12). |
| **Cart with two shoppers sharing a basket** | AI flags `CartSplit`; engine asks the cashier to confirm a split or merge. No automatic split in v1. |
| **Payment captured but order write fails** | The transaction rolls back; the payment-gateway idempotency key prevents double-charge on retry. The cart returns to `OPEN` with a domain error. |
| **Payment fails after cart was locked** | Cart returns to `OPEN`. Reservations remain valid for the configured retry window before being released. |
| **AI Engine offline** | All AI proposals stop. Cashiers continue manual POS flow with no degradation. Smart cart simply *isn't offered* during the outage. |
| **Backend offline (from edge node)** | AI Engine buffers events in a bounded local spool; events older than the spool budget are dropped with metrics. When backend recovers, events flush. Carts opened during the outage may begin "from now" once connectivity returns. |
| **Refund** | Refund is a new flow on a `CONVERTED` order — never a backwards cart edit. The order remains immutable; the refund writes a `Refund` row and a compensating `StockMovement(RETURN)`. |

---

# Multi-Branch Isolation

- A cart **MUST** carry `branch_id` (`NOT NULL`); the Cart Engine
  refuses to create one without it.
- The Redis index `cart:branch:{branchId}:open` is per branch; no
  cross-branch enumeration is possible.
- WebSocket topics are scoped per branch
  (`org.{orgId}.branch.{branchId}.cart.{cartId}`); subscription is
  permission-checked against the principal's `allowed_branch_ids`
  ([Authentication §Multi-Branch Security](13_AUTHENTICATION.md#multi-branch-security)).
- The AI Engine resolves a cart only inside the camera's branch; a
  proposal from a camera in Branch A can never affect a cart in
  Branch B.
- **Branch-level pricing (future-ready):** the price resolver is
  ordered `branch_override → org_base_price → catalogue_default`.
  v1 only uses the catalogue default; the seam exists.
- **Cross-branch transfers** are inventory movements (Inventory
  context), never cart movements. A customer who carries items
  between branches in v1 is treated as two separate sessions.

---

# Event Flow

### Pipeline (canonical)

```
[AI: CustomerDetected | TrackingSessionStarted]
        │
        ▼
[Cart Engine: open or attach cart]  →  CartCreated
        │
        ▼
[AI: ProductPickedUp + ProductRecognized]
        │
        ▼
[Cart Engine: AddItemToCart (txn: line + reservation)]
        │
        ▼
CartUpdated (event)
InventoryReserved (event)
        │
        ▼
[WebSocket Gateway → dashboard / cashier]
        │
        ▼
[Customer reaches checkout]
        │
        ▼
[Cart Engine: CheckoutInitiated → Payment Engine]
        │
        ▼
[Order Engine: OrderCreated + InventoryCommitted (txn)]
        │
        ▼
OrderCreated (event)
InventoryUpdated (event)
        │
        ▼
[Analytics consumers: footfall→conversion, sales, basket size]
[Notification consumers: receipt, low-stock alert if triggered]
[Audit consumers: audit log written inside the order txn]
```

### Cross-context consumers

- **Inventory module** consumes `InventoryReserved`, `InventoryReleased`,
  `InventoryCommitted`, `StockTransferred` events for its dashboards
  and re-order alerts.
- **Notification Center** consumes `CartAbandoned`,
  `OrderCreated`, `TheftSuspected` to fan messages to the right
  recipients on the right channels.
- **Analytics** consumes `OrderCreated`, `CartCreated`,
  `CustomerDetected` and updates `ConversionAggregate`,
  `FootfallAggregate`, `BasketAggregate` etc. via background jobs.
- **AI Engine** consumes `InventoryCommitted` so its in-memory
  "in-stock" view stays current and the planogram prior is
  accurate.

---

# Performance Design

### Latency targets

| Path | Target (p95) |
|------|--------------|
| AI event arrival → cart row updated | ≤ 200 ms |
| Cart row updated → WebSocket fan-out | ≤ 50 ms |
| End-to-end (camera → cart UI render) | ≤ 1 s |
| Checkout (cart frozen → order created on simulated payment) | ≤ 500 ms |
| Inventory commit reflected in dashboard gauges | ≤ 1 s |

### High-frequency event handling

- AI rule engine cooldowns and dedupe keep average per-cart event
  rates bounded to a few per second even during heavy shopping.
- The Cart Engine handles bursts via **per-cart serial processing**
  (one writer per cart at a time, queued behind the row lock), so
  contention is local and predictable.
- Background fan-out (analytics, notifications) runs on dedicated
  Celery queues so foreground cart latency is unaffected.

### Redis optimisation strategy

- Cart hashes are small and bounded (≤ tens of lines per cart).
- Per-branch open-cart index is cleaned on cart close / abandon.
- TTLs on every key — no permanent Redis keys for transactional
  data.
- Redis pub/sub channels are per branch + per cart, keeping
  fan-out tight.

### Event batching strategy

- The Cart Engine does **not** batch cart writes; each AI event is a
  single, small, transactional write.
- The analytics consumers **do** batch: aggregates update on a tick
  (e.g. once per second per branch) rather than per event, so DB
  write amplification stays low.
- Notifications batch only when policy allows (e.g. low-stock
  digest); transactional notifications (receipt, theft alert) send
  immediately.

---

# Security Model

### Cart tampering prevention

- All cart mutations go through the Cart Engine; clients **cannot**
  set totals, prices, or `version` directly. Totals are recomputed
  server-side on every mutation.
- Cart endpoints require `cart.create` / `cart.manage` permissions
  scoped to the branch.
- Optimistic concurrency with `version` prevents replay of stale
  cart-edit requests.

### AI spoofing protection

- The AI Engine authenticates as a service account with an API key
  scoped to the tenant and the camera ids it owns
  ([Authentication §AI Security](13_AUTHENTICATION.md#ai-security-model)).
- The Cart Engine re-checks **every** AI event:
  - The camera belongs to the presenting tenant + branch.
  - The cart belongs to the same branch.
  - The event's `occurred_at` is within a small skew window.
  - The event schema and `event_type@vN` are known and valid.
- Events that fail validation are rejected and audited as
  `ai.event.rejected`.

### Session hijacking prevention

- Cart subscribers authenticate over WebSocket with the same JWT
  scheme as REST. Tokens are short-lived; revocation closes affected
  connections within the documented SLO.
- Subscribers receive **only** the cart topics their role + branch
  scope allow.
- Customer companion app (future) uses a separate audience and
  cannot be issued staff tokens.

### Branch-level enforcement

- The principal's `allowed_branch_ids` derived at JWT issuance is
  authoritative; clients **cannot** override `branch_id` in cart
  endpoints.
- Cross-branch cart access requires an org-wide permission and is
  audited.
- Cross-tenant access is `super_admin` only and is per-action
  audited.

### Audit

- Sensitive transitions write `AuditLog` rows inside the same
  transaction:
  - Manual cart override (`cart.line.overridden`).
  - Cart lock and unlock (`cart.locked`, `cart.unlocked`).
  - Refund issued.
  - Cashier merging or splitting carts.

---

# System Integration

### AI Engine

- The Cart Engine **subscribes** to AI events via the AI Event
  Gateway (`ProductPickedUp`, `ProductReturned`,
  `CustomerDetected`, `TheftSuspected`, etc.).
- The Cart Engine **never** calls into the AI Engine. The AI Engine
  reads inventory snapshots from Redis (refreshed by the Cart
  Engine) — never from Postgres directly.

### Event Bus

- The Cart Engine **publishes** the canonical cart and inventory
  events listed in §Event Flow.
- The bus is the only fan-out mechanism between contexts —
  notifications, analytics, audit, and dashboards consume from the
  bus.

### Backend API

- The cart and order REST endpoints are the **only** ingress for
  client cart actions (cashier POS, dashboard reviewer, future
  customer app).
- Idempotency keys are required on mutating endpoints (cart add,
  cart remove, checkout) per BR-17.

### WebSocket layer

- The WebSocket gateway forwards per-cart and per-branch events to
  subscribers (see §Real-time Synchronization).
- The gateway authenticates the JWT at handshake; each `subscribe`
  is permission-checked.

### Inventory module

- The Inventory context **owns** `InventoryItem` and `StockMovement`.
- The Cart Engine **calls** the Inventory application service for
  reservations, releases, and commits — it does not write to
  inventory tables directly. This keeps the cross-context contract
  explicit and audit-friendly.

### Notification system

- The Notification Center consumes:
  - `OrderCreated` → optional receipt to customer (future).
  - `CartAbandoned` → optional summary for the customer (future).
  - `TheftSuspected` / `TheftDetected` → operator alerts.
  - `InventoryReserved` (after a threshold) → low-stock alerts to
    branch staff.

### Analytics

- Conversion, basket, and footfall aggregates consume cart and
  order events through scheduled or event-driven roll-ups
  ([System Design](SYSTEM_DESIGN.md)).

---

# Future Improvements

### Smart cart UX

- **Customer mobile companion** — live cart in the customer's hand;
  in-store self-checkout; remote pay.
- **Frictionless walk-out** (Amazon-Go-style) — fully AI-driven
  checkout for branches with full camera + sensor coverage; gated by
  customer enrolment + payment-method linking.
- **Real-time price hints** — show discounts and substitute
  suggestions inside the cart UI.

### Pricing and promotions

- **Branch-level pricing overrides** with effective dates.
- **Cart-level, line-level, customer-level promotions** as a
  pluggable promotion engine.
- **Bundle pricing** (buy-two-get-one), **loyalty discounts**,
  **time-of-day promotions**.

### Payments

- **Real payment gateways** (cards, wallets, QR / VietQR, BNPL) with
  the same idempotent interface the simulator implements.
- **Split tenders** (cash + card on one order).
- **Refund flows** with partial-line refunds and original-payment
  reversal.

### Inventory

- **Multi-warehouse / cross-branch reservation** so customers in
  Branch A can pay for goods to be picked from Branch B.
- **Lot / batch tracking** for goods that require it.
- **Expiry-aware reservations** (oldest-first for perishables).

### AI ↔ cart

- **Cross-camera shopper continuity** so a shopper who leaves one
  camera's field of view keeps the same cart without a recognition
  event.
- **Confidence-aware UI** that visually distinguishes
  AI-only-confidence lines from cashier-confirmed lines.
- **Operator feedback loop** with one-tap "wrong product" → enters
  the training-data governance pipeline.

### Operations

- **Cart-level audit trail** showing every AI event and operator
  action that shaped the cart, replayable inside the dashboard.
- **Cart insurance / shrinkage analytics** that combine
  `TheftSuspected`, `TheftDetected`, and inventory variance into
  branch-level shrinkage reports.

### Anti-goals (deliberately not on the plan)

- Letting AI write directly to `ShoppingCart` or `InventoryItem`.
- Multi-branch cart merge as an automatic operation.
- Long-lived (> hours) open carts.
- Storing payment instrument data inside the cart.
- Negotiating final prices in the client UI.

---

*This document is the canonical Smart Cart, Checkout Engine, and
Inventory Sync design. Any change to cart lifecycle, AI mapping,
checkout flow, or inventory rules requires a PR that updates **only
this file** (and, when needed, an ADR explaining the rationale).*
