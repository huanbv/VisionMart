# VisionMart — MVP Finalization, Demo Scenario & Productization

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/MVP_DEMO_PLAN.md`
> **Owner:** Lead Product Architect & Technical Lead
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** MVP finalization, live-demo readiness, academic
> defence support, and productization plan. **No new feature design.**
> No code, no APIs, no DDL. Where this document conflicts with
> implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract](ARCHITECTURE_CONTRACT.md) ·
> [Product Backlog](PRODUCT_BACKLOG.md) ·
> [Development Roadmap](05_DEVELOPMENT_ROADMAP.md) ·
> [System Design](SYSTEM_DESIGN.md) ·
> [Authentication](13_AUTHENTICATION.md) ·
> [AI Overview](20_AI_OVERVIEW.md) ·
> [Camera Manager](21_CAMERA_MANAGER.md) ·
> [Cart Engine](26_CART_ENGINE.md) ·
> [Dashboard & Analytics](37_DASHBOARD.md) ·
> [Notification & Integration Hub](15_NOTIFICATION_CENTER.md) ·
> [Deployment Plan](07_DEPLOYMENT_PLAN.md)

---

# MVP Scope

### Guiding principle

The MVP demonstrates **the whole value loop, end to end** — camera
to AI to cart to inventory to dashboard to notification — on **a
single branch, a single organization, a small camera count**. Depth
beats breadth: every included feature must work reliably during a
live demo. Anything that does not is **out**.

### In MVP

| Area | In MVP |
|------|--------|
| **Identity & Access** | Email/password login; JWT auth; RBAC with seed roles (`super_admin`, `org_admin`, `branch_manager`, `cashier`, `staff`, `viewer`, `service:ai-engine`); per-branch scope. |
| **Organization & Branch** | One demo organization with one branch; multi-branch support exists structurally but only one branch is exercised. |
| **Catalog** | Categories + Products (≈ 30–60 SKUs covering 3–5 categories); product images. |
| **Inventory** | InventoryItem per (product, branch); StockMovement on every change; low-stock alerts. |
| **Camera Management** | 1–3 cameras (mix of one entry-zone, one shelf, optionally one checkout); registration; health + status. |
| **AI Pipeline** | YOLOv8 detection + ByteTrack tracking + ProductPickedUp/Returned rule + simple shelf-empty rule + queue-length rule. Face recognition **off** in the demo (no consent step). |
| **Smart Cart** | AI-driven cart with cashier confirmation for `ai_pending` lines; pick-up / return; checkout simulation. |
| **Checkout** | Cart validation; payment **simulation** (always-success); Order + OrderLine + Payment + StockMovement(SALE) in one transaction. |
| **Real-time Dashboard** | Live tiles (active customers, open carts, items picked / min, queue length, camera health); alerts panel; heatmap overlay on a static floor plan; recent events feed. |
| **Notifications** | In-app via WebSocket for queue + camera offline + low-stock + theft-suspected; email-channel implemented but disabled in the demo to avoid network dependence. |
| **Event System** | Internal EventBus (in-memory) with Redis pub/sub for cross-replica fan-out; AI Event Gateway. |
| **Observability** | Structured logs; basic Prometheus metrics; one Grafana overview dashboard. |
| **Deployment** | Docker Compose single-host deployment with optional GPU profile; reproducible from the repo. |

### Out of MVP (explicit non-goals)

- Real payment gateways (cards, wallets, QR).
- SSO / SAML / OIDC / WebAuthn / 2FA.
- Multi-organization SaaS provisioning UI (the data model supports
  it, but onboarding flows are manual).
- Mobile apps (cashier or customer).
- Customer face recognition (kept out of the demo for privacy and
  consent simplicity; the pipeline exists).
- Cross-branch transfers / merges.
- Real promotions / discounts engine (the seam exists; no active
  plugins).
- ERP / POS integrations through webhooks (the Integration Hub
  exists; no demo subscribers).
- Reporting module beyond what the dashboard renders.
- Kubernetes deployment (Tier 2 design is documented; demo runs on
  Tier 1 Compose).

### Prioritization (demo-readiness ladder)

| Tier | Why it's at this tier |
|------|------------------------|
| **P0 — Must work flawlessly** | Login, RBAC, camera health tiles, AI pick/return → cart update, checkout, inventory deduction, live alerts. |
| **P1 — Must work** | Heatmap overlay, queue alert, low-stock alert, audit log on sensitive actions. |
| **P2 — Nice to have** | Email notification path, model registry deploy flow, planogram-mismatch event, theft-suspected alert. |
| **P3 — Out** | Anything not in this document. |

---

# Demo Scenario

### One-paragraph narrative

> *A shopper enters the demo store. A ceiling camera spots them; the
> dashboard lights up an `Active Customers` tile and a heatmap blob
> at the entrance. The shopper walks to the shelf, picks up a bottle.
> Within a second, the Smart Cart UI on the cashier station shows a
> new line — recognised SKU, quantity 1 — and the inventory tile
> ticks down. The shopper returns the bottle; the line disappears and
> stock returns. They pick a different SKU, head to the checkout zone,
> the queue indicator briefly turns amber, the cashier completes the
> simulated payment, an `Order #1042` toast appears on the dashboard,
> inventory updates again, and the audit log records the transaction.
> Total elapsed time: about 90 seconds. Zero manual entry.*

### Step-by-step scripted scenario

| # | Trigger | What you do | What the audience sees | Underlying flow |
|---|---------|-------------|------------------------|-----------------|
| 1 | Demo start | Presenter logs in as `branch_manager`. | Login → branch dashboard with live tiles, all green camera health. | Authentication §Authorization Flow. |
| 2 | Customer enters | A confederate (or pre-recorded clip) walks into the entry zone. | `Active customers` increments to 1; heatmap blob appears at entry. | AI: `TrackingSessionStarted`; analytics counter; live tile WebSocket update. |
| 3 | Shopper approaches the shelf | They stand near a shelf for ~2 s. | Heatmap intensifies near the shelf; dwell counter ticks. | AI: detections in shelf zone; dwell aggregate updated. |
| 4 | Pick up product A | Confederate picks one SKU. | A cart tile appears with `Cart #C-001` and Line: SKU-A × 1. | AI: `ProductPickedUp` + `ProductRecognized` ≥ 0.85; Cart Engine `AddItemToCart`; `InventoryReserved`. |
| 5 | Return product A | They put it back. | Line disappears; stock count restored. | AI: `ProductReturned`; Cart Engine `RemoveItemFromCart`; `InventoryReleased`. |
| 6 | Pick up product B | A different SKU. | New cart line: SKU-B × 1. | Same as step 4. |
| 7 | Pick up product C | Add a second item. | Cart shows two lines; total updates. | Same. |
| 8 | Move to checkout | Confederate walks to the checkout zone. | Queue tile shows length 1; if a second confederate joins, briefly turns amber. | AI: `QueueDetected`; alerts panel updates; cooldown prevents storm. |
| 9 | Cashier completes payment | Click "Charge" on the cashier UI. | Spinner → success toast → `Order #1042` appears on the dashboard. | Cart Engine: `CheckoutInitiated` → simulated payment → Order + Payment + StockMovement in one transaction; `OrderCreated`; `InventoryUpdated`. |
| 10 | Audit log | Presenter switches to the audit tab. | Recent rows: `cart.checkout.initiated`, `payment.captured`, `order.created`. | Synchronous audit writes inside the order transaction. |
| 11 | Camera failure (controlled) | Disconnect a camera (unplug or block via firewall). | Camera tile turns red; an alert appears in the panel. | Camera Manager: `CameraDegraded` → `CameraOffline`; Notification routed to manager. |
| 12 | Recovery | Reconnect the camera. | Tile returns to green within seconds. | Reconnect probe; `CameraOnline`. |
| 13 | Closing | Switch to the analytics tab. | Hourly footfall, picks, conversion, and heatmap of the demo session. | Aggregates populated by the demo's own events. |

### Backup track (if something doesn't trigger)

- If AI doesn't recognise a pick within ~3 s, the cashier
  **manually confirms** the suggested line; the same backend flow
  runs. This is part of the *hybrid* cart pattern and is **not a
  failure mode** — it's a designed behaviour the presenter can
  highlight.

---

# Demo Architecture

### Demo environment

- **Single host** (laptop or small workstation) running Docker
  Compose with the GPU profile if a GPU is available; otherwise CPU
  with reduced FPS.
- All services run in one project: Nginx, Backend, Workers,
  AI Engine, Postgres, Redis, MinIO, Frontend (served by Nginx),
  Observability (optional).
- **One isolated network** (private SSID or wired switch) — the demo
  must not depend on the venue's Wi-Fi.
- A small **demo cluster of cameras** (1–3) or a **virtual camera
  source** (see below).

### Preloaded data strategy

The demo starts from a known-good baseline created by a seed
script run once before the session begins:

- 1 organization, 1 branch, 1 floor plan with named zones (entry,
  aisle, checkout).
- 7 users covering each seed role + one AI service account.
- 3–5 categories, 30–60 products with images and unit prices.
- Inventory positioned so a demo pick reduces stock visibly (e.g.
  start at 12 units for "hero" SKUs).
- 1–3 cameras registered with the demo stream URLs.
- 1 model registration active per pipeline.
- An empty AuditLog, empty AIEvent table, empty Notifications — the
  demo populates them live.

### Camera source: real or simulated

| Option | When to use | Notes |
|--------|-------------|-------|
| **Real cameras** | When demo space supports it (1–3 IP cameras on a private VLAN). | Best showcase, but venue-sensitive. |
| **Camera simulator** | When venue networking is unknown or no cameras available. | A small RTSP server replays a curated MP4 in a loop, exposing an RTSP endpoint identical to a real camera. |
| **Hybrid** | One real camera + simulators for additional angles. | Mitigates risk; lets you showcase a "real" tile while extra tiles add visual richness. |

### AI inference mode

- **Live inference (default):** YOLOv8 + ByteTrack run on the GPU /
  CPU as in production.
- **Replay-augmented fallback (always loaded):** a deterministic
  **event-replay** mode can be enabled per camera so a recorded
  sequence of `AIEvent`s plays back on cue. This is the absolute
  safety net: even if every model breaks, the dashboard and the
  cart still demonstrate the full flow.
- The fallback writes the same `AIEvent` envelope as live AI and
  goes through the same AI Event Gateway — there is **no shortcut**
  through validation, scope, or audit.

### Network setup for stability

- Wired Ethernet between camera(s) / simulator and the host wherever
  possible.
- Private SSID for the host's external internet (if any) to avoid
  hotel/venue captive portals.
- TLS certificate **bundled and valid offline** (self-signed for
  internal hostnames is acceptable for a demo; the SPA trusts a
  pre-imported root).
- All third-party calls **disabled** in the demo configuration —
  no email send, no analytics beacon, no external webhook.

---

# Core Features

The MVP feature set is exactly the *In MVP* table from §MVP Scope.
This section restates the *finalisation* status:

| Area | Final design ref | Finalisation status |
|------|------------------|----------------------|
| Authentication & RBAC | [13_AUTHENTICATION.md](13_AUTHENTICATION.md) | ✅ Frozen for MVP. |
| Camera Management | [21_CAMERA_MANAGER.md](21_CAMERA_MANAGER.md) | ✅ Frozen for MVP. |
| AI Detection Pipeline | [20_AI_OVERVIEW.md](20_AI_OVERVIEW.md) | ✅ Frozen for MVP (face recognition disabled in demo). |
| Smart Cart | [26_CART_ENGINE.md](26_CART_ENGINE.md) | ✅ Frozen for MVP. |
| Inventory Sync | [26_CART_ENGINE.md](26_CART_ENGINE.md) + [10_DATABASE_DESIGN.md](10_DATABASE_DESIGN.md) | ✅ Frozen for MVP. |
| Real-time Dashboard | [37_DASHBOARD.md](37_DASHBOARD.md) | ✅ Frozen for MVP. |
| Event System | [15_NOTIFICATION_CENTER.md](15_NOTIFICATION_CENTER.md) | ✅ Frozen for MVP. |
| Notifications | [15_NOTIFICATION_CENTER.md](15_NOTIFICATION_CENTER.md) | ✅ Frozen for MVP (in-app only; email path tested but disabled). |
| Deployment | [07_DEPLOYMENT_PLAN.md](07_DEPLOYMENT_PLAN.md) | ✅ Tier 1 (Compose) used. |

> Anything not in this table is **out of MVP**. PRs adding scope to
> MVP require explicit approval.

---

# Performance Optimization

> The goal is **demo stability**, not benchmark numbers. We trade
> peak throughput for predictable latency and zero surprises.

### AI inference tuning for the demo

- **Target FPS reduced to 3–5 fps per camera** (down from up to
  30 fps in production). Lower frame load = lower latency variance.
- **Model**: YOLOv8 *small* (or *medium* if GPU has headroom);
  bigger models are not used in the demo.
- **Batch window**: tight (≤ 10 ms) — alone frames dispatch
  immediately to keep tail latency low.
- **Recognition index**: pre-warmed at startup; warm-up smoke
  detection runs before the doors open.

### Load reduction

- Disable heavy pipelines that aren't on the demo path
  (face recognition, planogram, motion-after-hours).
- Lower the AI Engine's spool / queue caps so backpressure shows up
  early as visible drops on metrics rather than as latency spikes
  on tiles.
- Set per-branch low-stock thresholds high enough that one demo
  pick triggers the alert (engaging the audience), without flooding
  the panel.

### Latency control

- **Live tile p95 ≤ 1 s**, end-to-end from camera frame to dashboard
  update; the **target** is sub-500 ms.
- Cashier "Charge" → order toast **≤ 500 ms** on the demo host.
- WebSocket fan-out tested with a connected dashboard + cashier UI
  during pre-checks.

### Fallbacks (operational, before failover)

- If the GPU saturates, the engine **drops to CPU** automatically
  on the AI Engine variant configured for the demo host.
- If the camera's effective FPS falls below threshold, the
  dashboard's camera tile shows a `degraded` badge but the cart
  flow continues using the hybrid (cashier-confirm) path.

---

# Fail-safe System

> A demo that **degrades gracefully** beats a demo that **crashes
> beautifully**. The platform's normal failure rules apply, plus
> demo-specific safety nets.

### Camera fails during demo

- **Detection:** stream read times out; AI Engine marks the camera
  `degraded` then `offline`.
- **UI behaviour:** tile turns amber → red; an alert appears in the
  panel. The presenter can use this as a *talking point* about
  reliability ("watch how the system tells me a camera died").
- **Recovery:** the demo's *secondary* camera (or its simulator
  twin) keeps the dashboard alive; the script step shifts to
  "show recovery" by reconnecting the disconnected stream.

### AI fails during demo

- **Detection:** rule engine stops emitting; AI Event Gateway sees
  no events for the camera in a configured window.
- **UI behaviour:** dashboard shows "AI degraded" badge; cart flow
  switches to **hybrid mode** (cashier scans / confirms).
- **Recovery:** the presenter can enable the **event-replay
  fallback** in one click — a recorded `AIEvent` sequence flows into
  the gateway and the cart UI populates as if AI were live. The
  audience sees the same demo; the *failover* is itself a feature
  story ("AI was down; the same architecture kept us running").

### Network is unstable

- The demo host runs the whole platform locally; **no internet
  is required** for the demo path.
- Inter-camera/host wiring is Ethernet (preferred) or a dedicated
  SSID — never venue Wi-Fi.
- All external calls (email, webhooks, telemetry) are disabled in
  the demo configuration.

### Offline / "air-gap" demo mode

- The Compose project can run completely offline once images are
  pre-pulled.
- Model artefacts, product images, and the event-replay clips ship
  with the demo bundle.
- The SPA is served by Nginx from the same host; no CDN.

### Pre-recorded fallback video

- A curated MP4 of the demo scenario is **always available** on the
  presenter's machine. If everything goes wrong, the presenter
  switches to the video while explaining the architecture from the
  slides. The judges still see the value loop.

---

# UI/UX Finalization

### Dashboard layout (final)

| Region | Widgets (default) |
|--------|--------------------|
| **Header** | Org / branch picker (locked to demo branch); user menu; environment badge (`DEMO`). |
| **Top KPI strip** | Active customers · Open carts · Items picked / min · Orders today · Revenue today (simulated currency). |
| **Live tiles row** | Camera health · Queue strip · Alerts panel · Low-stock chips. |
| **Centre canvas** | Tabbed: **Floor heatmap** | **Camera tile grid** | **Live events feed**. |
| **Side panel** | Selected cart (when one is highlighted) showing lines + totals + provenance (`ai`, `manual`, `hybrid`). |
| **Bottom strip** | Recent orders list with one-click drill-down. |

### Cashier UI (final)

- One screen.
- Cart lines on the left (with `added_via` icons).
- Suggested AI lines highlighted, with **Confirm** / **Reject**
  buttons (hybrid mode).
- "Charge" button on the right; result toast.
- Status badge in the corner: `AI live` / `AI degraded` /
  `AI replay`.

### Simplicity rules for demo

- **No clutter.** Every visible widget exists for a script step.
- **No dead links.** Tabs that show empty content are removed for
  the demo.
- **Stable layout.** Tile positions are pinned; no auto-rearrange
  while the audience watches.
- **High-contrast palette.** Status colours (green / amber / red /
  grey) read from the back of a projection room.
- **One-second freshness badge** on every live tile (e.g. "updated
  2 s ago") to demonstrate real-time.

---

# Demo Data Strategy

### Pre-seeded baseline (loaded once)

| Dataset | Volume | Notes |
|---------|--------|-------|
| Organization, Branch, Floor plan, Zones | 1 / 1 / 1 / 4 | Entry, aisle, shelf, checkout. |
| Users | 7 | One per role + `service:ai-engine`. |
| Roles, Permissions, Assignments | Full seed set | Demo-friendly defaults. |
| Categories | 3–5 | E.g. Beverages, Snacks, Personal Care, Household, Fresh. |
| Products | 30–60 | With names, images, prices, barcodes; "hero" SKUs marked. |
| Inventory | One row per product × branch | Hero SKUs start at 12 units; others at 5–20. |
| Cameras | 1–3 | With probe data and `online` status. |
| ModelRegistration | One active per pipeline | Pre-warmed. |
| Notifications, Carts, Orders, AIEvents | Empty | Populated live by the demo. |

### Simulated customer flow

- 1 confederate as the primary shopper.
- Optional 2nd confederate to trigger the queue alert.
- Choreography rehearsed: enter → dwell → pick → return → pick →
  pick → checkout.

### Fake product catalog

- A small, visually distinct catalog so detection is *clearly*
  attributable on stage.
- Hero SKUs are chosen for **visual contrast** (different colours,
  shapes, sizes) so a recognition margin demo is convincing.
- Product images sourced or generated; no copyrighted assets.

### Controlled AI scenarios

- A short pre-recorded **event-replay clip** mirrors the
  choreography exactly. It is **only triggered** if live AI fails
  or as a "show me the same outcome from a recorded session"
  bonus slide.

---

# Demo Script

> Roughly 12–15 minutes of speaking + 2–3 minutes of buffer. Adjust
> per audience.

### 1) Opening (≈ 1 min)

> "Good morning. I'm presenting VisionMart, an AI Smart Retail
> Platform that turns ordinary store cameras into an intelligent
> retail operations layer. Today I'll show you the full loop —
> camera to AI to cart to checkout — running on this laptop, and
> I'll walk you through the architecture that makes it production-
> ready."

### 2) Problem statement (≈ 2 min)

> "Modern retail loses billions a year to checkout friction,
> out-of-stock shelves, queue abandonment, and shrinkage. Every
> store already has cameras — but they're recording, not
> *understanding*. VisionMart converts those existing cameras
> into a real-time operations dashboard: who's in the store, what
> they're picking up, what's running low, and what to do about it."

### 3) Architecture explanation (≈ 3 min, slides)

- Slide: **layered architecture** — Camera → AI Engine → EventBus →
  Backend → (Cart / Inventory / Notification / Dashboard).
- Slide: **AI proposes; backend decides** — explain why this
  separation matters for correctness and trust.
- Slide: **stack & deployment** — Python/FastAPI backend,
  YOLOv8+ByteTrack AI Engine, Postgres + Redis + MinIO,
  React/TS dashboard, Docker Compose deployment.
- Slide: **bounded contexts + modular monolith** — show how the
  codebase will scale to SaaS without rewrites.

### 4) Live demo (≈ 6–8 min)

Walk through the §Demo Scenario step-by-step table. Narrate
**what** is happening on screen and **why** the architecture made
it possible (e.g. "this is the event bus fanning out the cart update
to the dashboard via WebSocket; the same event also writes the
inventory reservation in the database").

### 5) Resilience moment (≈ 1 min)

- Unplug a camera; show the alert.
- Re-plug; show recovery.
- Optionally trigger the AI degraded → replay fallback and explain
  "even if the model is down, the same architecture keeps the
  business running."

### 6) Business value (≈ 1 min)

Brief framing per §Business Value below.

### 7) Productization preview (≈ 1 min)

> "What you saw is a single branch on a single laptop. The same
> codebase scales to multi-tenant SaaS without architectural
> rewrites — the design is documented in our Architecture Contract
> and our roadmap takes us from MVP to multi-region SaaS in 14
> releases."

### 8) Closing (≈ 30 s)

> "VisionMart proves that you don't need to rip out and replace a
> store's hardware to make it smart. With cameras, modern AI, and
> a clean architecture, the platform delivers real-time retail
> intelligence today, and a path to enterprise SaaS tomorrow.
> Thank you — happy to take questions."

### Q&A preparation (likely questions)

| Question | One-line answer |
|----------|------------------|
| Privacy / face recognition? | Off by default; consent-gated when on; embeddings purged on withdrawal. |
| AI accuracy? | Recall-first detector + precision-first rules with explicit thresholds; cashier confirms low-confidence lines. |
| What if AI is wrong? | AI proposes; the backend decides. Cashier can reject any line; audit log records every override. |
| Scalability? | Stateless backend, per-GPU AI workers, consistent-hash camera-to-node assignment, designed for KEDA on Kubernetes. |
| Cost? | Per-branch cost dominated by one GPU per ~16–32 cameras + small VPS for backend + standard managed services in SaaS tier. |
| Compliance? | Audit-first design; per-tenant data isolation; consent workflow; per-region deployment option. |

---

# Business Value

### Why this matters for retail

- **Higher conversion.** Real-time queue alerts and faster checkout
  recover walk-aways.
- **Less shrinkage.** Theft-suspected signals + evidence snapshots
  shorten investigation cycles.
- **Less out-of-stock.** Shelf-empty AI events alert staff before
  customers notice.
- **Better staffing.** Hourly footfall + queue + wait metrics
  pinpoint when to add cashiers.
- **Smarter merchandising.** Heatmaps + interaction-to-purchase
  ratios drive layout and assortment decisions.

### Why this matters for the operator

- **One dashboard** for the branch instead of three disconnected
  systems (POS, CCTV, inventory).
- **One audit trail** spanning AI events, cashier actions, and
  business state.
- **Existing cameras** are reused — no rip-and-replace.

### Why this matters for VisionMart as a company

- **Productizable from day one** — multi-tenant data model,
  multi-branch by design, event-driven integrations.
- **Defensible architecture** — explicit boundaries (AI Engine vs
  Backend, modular monolith vs distributed sprawl) reduce
  long-term maintenance cost.
- **Compliance-friendly** — consent gating, audit log, per-region
  options.

---

# Thesis Support

### Diagrams to present

1. **Layered architecture** — Client → Edge → API → Event/Worker/
   Integration → AI → Data → Storage
   ([07_DEPLOYMENT_PLAN.md](07_DEPLOYMENT_PLAN.md)).
2. **AI pipeline** — Frames → Preprocess → YOLOv8 → ByteTrack →
   Rules → Events ([20_AI_OVERVIEW.md](20_AI_OVERVIEW.md)).
3. **Smart cart lifecycle** — CartCreated → ItemAdded/Removed →
   CheckoutInitiated → OrderCreated → CartClosed
   ([26_CART_ENGINE.md](26_CART_ENGINE.md)).
4. **Event flow** — AI → AI Event Gateway → EventBus → consumers
   ([15_NOTIFICATION_CENTER.md](15_NOTIFICATION_CENTER.md)).
5. **Multi-tenant + multi-branch isolation** with 5-layer defence
   in depth ([13_AUTHENTICATION.md](13_AUTHENTICATION.md)).
6. **Database / ERD** for the analytics + AI tables
   ([10_DATABASE_DESIGN.md](10_DATABASE_DESIGN.md)).
7. **Two-tier deployment** — Compose (Tier 1) and Kubernetes
   (Tier 2) ([07_DEPLOYMENT_PLAN.md](07_DEPLOYMENT_PLAN.md)).

### Key explanation points

- The cardinal rule "**AI proposes; backend decides**" — why this
  matters for correctness, auditability, and trust.
- The **modular monolith with bounded contexts** — gives the
  development velocity of a monolith and the evolutionary path of
  microservices.
- **Event-first design** — `event_id` + `correlation_id` give
  end-to-end traceability for every business outcome.
- **Two-tier deployment** — the same images run from a laptop to a
  multi-region cluster.

### Research / engineering contributions

1. A **production-grade reference architecture** for AI-driven
   brick-and-mortar retail that separates perception from decision
   without sacrificing latency.
2. A **business-rule layer** that converts AI signals into
   transactions with explicit, tunable confidence thresholds and
   debouncing — preventing the common pitfall of "the model said
   yes, so we changed the bill".
3. A **multi-tenant data model** that supports row-level isolation
   today and schema-per-tenant tomorrow without code changes.
4. A **two-tier deployment model** that lets the same codebase ship
   to a single store and to a multi-region SaaS cluster.
5. A **comprehensive design documentation set** (Architecture
   Contract, Domain Model, ADRs, Database Design, AI/Camera/Cart
   designs, Deployment Plan) that operationalises Clean
   Architecture + DDD + SOLID for an AI-heavy domain.

### Technical achievements (talking points)

- **YOLOv8 + ByteTrack** real-time pipeline with explicit
  per-stage latency budgets (camera → user ≤ 250 ms p95).
- **Smart cart** with reservation/commit inventory model and
  oversell prevention via row-level locking.
- **WebSocket fan-out** with offset-aware reconnect and
  per-subscription permission checks.
- **Transactional outbox + idempotent consumers** for delivery
  correctness without exactly-once illusions.
- **Time-partitioned analytics** with idempotent roll-ups and
  bucket immutability.
- **CI/CD pipeline** with lint, type-check, unit + integration
  tests, security scan, image build, and digest-pinned promotion.

---

# Productization Strategy

### Path from MVP to product

1. **Beta with 1–3 paying tenants** on Tier 1 (Compose on dedicated
   VPS per tenant).
2. **Onboarding wizard** for new organizations + branches +
   cameras.
3. **Real payment gateways** + **SSO** + **email/SMS channels**.
4. **Migration to Tier 2 (Kubernetes)** with managed Postgres +
   Redis + S3.
5. **Marketplace of integrations** (ERP, POS, loyalty, BI).
6. **Multi-region** active/active for enterprise tenants.

### Multi-tenant expansion

- Already designed: **row-level discriminator** with org-wide RBAC,
  branch-scoped roles, and per-tenant API keys.
- **Schema-per-tenant** for premium customers without code changes.
- **Per-tenant signing keys** and rate budgets for blast-radius
  isolation.

### Subscription model (future)

| Tier | What's included | Target |
|------|------------------|--------|
| **Starter** | 1 branch, ≤ 4 cameras, in-app notifications, monthly reports. | Independent stores. |
| **Pro** | Multi-branch, ≤ 16 cameras, email/SMS, webhooks, basic integrations. | Chains. |
| **Enterprise** | Unlimited branches, GPU autoscaling, SSO, custom retention, dedicated environments, broker bridges, per-region deployment, SLA. | Large retailers. |
| **Add-ons** | Face recognition, advanced theft analytics, customer mobile app, premium integrations, custom reports. | Per tenant. |

### Monetisation principles

- Charge for **value delivered** (active cameras, branches, AI
  pipelines enabled) — not for raw API calls.
- **Predictable pricing** with caps; the platform alerts the
  tenant before they hit limits, never silently rate-limits.
- **No data lock-in:** tenants can export their data
  (catalog, customers with consent, audit, aggregates).

### Anti-monetisation principles

- No selling of customer data or aggregated profiles to third
  parties.
- No "AI surprise charges" — model upgrades are part of the
  subscription.
- No vendor lock-in via proprietary file formats; events are
  documented and portable.

---

# Final Architecture Summary

```
[Camera (RTSP/RTSPS)]
        │
        ▼
[AI Engine]
   - Stream Processor (per camera)
   - YOLOv8 detection (GPU/CPU)
   - ByteTrack tracking
   - Recognition (optional, consent-gated)
   - Business Rule Engine
   - Event Publisher (idempotent, signed, scoped)
        │ AIEvent + optional Snapshot
        ▼
[Backend — AI Event Gateway]
   - Authenticates service account
   - Validates scope, schema, timestamps, confidence
   - Persists AIEvent (partitioned), DetectionResult (sampled)
        │
        ▼
[EventBus  (InMemoryEventBus + Redis pub/sub)]
        │
        ├──► [Smart Cart Engine]
        │       - AI → cart mapping (with thresholds + cooldown)
        │       - One-transaction inventory reservation
        │       - Hybrid cashier confirmation
        │
        ├──► [Order Engine]
        │       - Cart freeze, simulated payment
        │       - Order + OrderLine + Payment + StockMovement(SALE)
        │         in one transaction
        │
        ├──► [Inventory Service]
        │       - InventoryItem + StockMovement (auditable)
        │       - Low-stock alerts
        │
        ├──► [Notification Center]
        │       - Priority-graded routing
        │       - In-app (WebSocket) + email + webhook
        │
        ├──► [Analytics / Dashboard]
        │       - Redis hot counters
        │       - Postgres partitioned aggregates
        │       - WebSocket live tiles + REST drill-down
        │
        ├──► [Audit]
        │       - Append-only, partitioned, correlation_id-tracked
        │
        └──► [Integration Hub]
                - HMAC-signed webhooks
                - Inbound API keys
                - DLQ + replay

Data: PostgreSQL (primary + replica) · Redis (cache + pub/sub) ·
      MinIO (snapshots, embeddings, models, exports) · Cold archive.

Edge: Nginx (TLS + rate limits + security headers).
Auth: JWT (short access, opaque refresh, rotation, revocation).
Deployment: Docker Compose (Tier 1) → Kubernetes (Tier 2).
```

### One-line summary

> **VisionMart turns existing store cameras into a real-time retail
> operations platform — perception by AI, decisions by the backend,
> visualisation in the dashboard, integrations through the hub — on
> an architecture that runs identically from a laptop to a
> multi-region SaaS cluster.**

---

*This document is the canonical MVP finalisation, demo plan, and
productization brief. Any change to MVP scope, demo scenario, or
productization strategy requires a PR that updates **only this file**
(and, when needed, an ADR explaining the rationale).*
