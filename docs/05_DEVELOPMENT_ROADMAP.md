# VisionMart — Development Roadmap

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/05_DEVELOPMENT_ROADMAP.md`
> **Owner:** Engineering / Product
> **Status:** v1.0 — Initial roadmap

---

## How to Read This Document

- Releases are **incremental and additive**: every release inherits everything from previous releases unless explicitly deprecated.
- Each release is scoped to be deliverable in **2–4 sprints** (the heavier ones may span more, and are flagged accordingly).
- "**Done**" for any release means: all features merged + all testing goals met + deployment goal verified in the target environment + release notes published.
- Story IDs reference [`docs/PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md). Cross-links use the `VM-<EPIC>-<NN>` convention.
- Dependencies between releases are listed up front so the release plan can be re-sequenced without breaking the dependency graph.

---

## Release Map

| Version | Theme | Status | Depends On |
|---------|-------|--------|------------|
| **v0.1** | Foundation | Planned | — |
| **v0.2** | Backend Core | Planned | v0.1 |
| **v0.3** | Authentication | Planned | v0.2 |
| **v0.4** | Product Management | Planned | v0.3 |
| **v0.5** | Inventory | Planned | v0.4 |
| **v0.6** | Camera Management | Planned | v0.3 |
| **v0.7** | AI Detection | Planned | v0.6 |
| **v0.8** | Smart Cart | Planned | v0.5, v0.7 |
| **v0.9** | Dashboard | Planned | v0.5, v0.7 |
| **v1.0** | **MVP — Production Launch** | Planned | v0.1 → v0.9 |
| **v1.1** | Analytics | Planned | v1.0 |
| **v1.2** | Multi-Branch | Planned | v1.0 |
| **v1.3** | Cloud | Planned | v1.0 |
| **v2.0** | Enterprise | Planned | v1.1, v1.2, v1.3 |

---

# v0.1 — Foundation

> Stand up the repository, container stack, configuration, logging, and CI so that every subsequent release is built on a reliable, observable baseline.

### Objectives

- Establish the monorepo layout and project constitution.
- Make the full stack runnable on any developer machine with `docker compose up`.
- Enforce code quality from the very first commit via CI.

### Features

- Repository scaffolding: `backend/`, `frontend/`, `ai-engine/`, `docker/`, `docs/`, `scripts/`.
- `Dockerfile` per service (multi-stage, non-root runtime).
- `docker-compose.yml` for Postgres, Redis, MinIO, Nginx, Backend, AI Engine, Frontend.
- Nginx reverse proxy with TLS-ready config and security headers.
- Centralised configuration via `pydantic-settings` (backend) and `import.meta.env` (frontend).
- Structured JSON logging + `X-Request-ID` propagation.
- `/health` (liveness) and `/ready` (readiness) endpoints.
- CI pipeline: lint, type-check, unit tests, image build (backend + frontend + ai-engine).

### Backlog Coverage

`VM-INFRA-01`, `VM-INFRA-02`, `VM-INFRA-03`, `VM-INFRA-04`, `VM-INFRA-05`, `VM-INFRA-08`, `VM-INFRA-09`

### Dependencies

- None.

### Testing Goals

- Unit-test coverage ≥ 70% on shared utilities (settings, logging, middleware).
- CI runs in under 10 minutes for a typical PR.
- Healthchecks for every Compose service pass within 60 s of `up`.

### Deployment Goals

- `docker compose up -d` produces a healthy stack on Linux, macOS, and Windows (WSL2).
- A single-node staging VM can host the stack behind Nginx with valid TLS.

### Expected Deliverables

- Tagged release `v0.1.0` on GitHub.
- `README.md` with full local-setup instructions.
- `.env.example` documenting every variable.
- Published Docker images for `backend`, `frontend`, `ai-engine` (on GHCR or equivalent).

---

# v0.2 — Backend Core

> Add the persistence, async runtime, and architectural primitives every business module will depend on.

### Objectives

- Implement the Clean Architecture / DDD skeleton (Entities, Repositories, EventBus, DI providers).
- Establish the database foundation: SQLAlchemy 2.x async + Alembic + connection pooling.
- Wire up the Celery worker for background work.

### Features

- `Base`, `Entity`, `ImmutableEntity`, `AssociationBase`, naming conventions, mixins.
- Async session factory with tuned pool, `expire_on_commit=False`.
- Generic async `BaseRepository[ModelT]` with soft-delete semantics.
- `EventBus` interface + in-memory implementation.
- Alembic configured for autogenerate against the central model registry.
- Celery app, broker, result backend wired to Redis.
- DB-aware `/ready` endpoint (verifies DB with `SELECT 1`).
- Initial module folders for all 10 bounded contexts (tenancy, identity, customer, employee, camera, catalog, inventory, sales, notification, audit) with bare ORM models.

### Backlog Coverage

`VM-INFRA-06`, `VM-INFRA-07`, `VM-ORG-01` (model only), and the entity scaffolding referenced by every later epic.

### Dependencies

- v0.1.

### Testing Goals

- Schema autogenerates a stable initial migration with no diffs.
- Repository CRUD + soft-delete unit-tested against a real (Dockerised) Postgres.
- Celery round-trip (enqueue → execute → result) covered.

### Deployment Goals

- `alembic upgrade head` succeeds on a fresh and on an existing database.
- `scripts/db-init.sh --initial` bootstraps the schema in one command.

### Expected Deliverables

- Tagged release `v0.2.0`.
- First migration committed under `backend/alembic/versions/`.
- Updated `docs/10_DATABASE_DESIGN.md` and `docs/11_DATABASE_ERD.md`.

---

# v0.3 — Authentication

> Lock down the platform with a production-grade identity and authorization layer.

### Objectives

- Ship secure login, token, and RBAC mechanics that every later release will rely on.
- Establish multi-tenant isolation rules at the request boundary.

### Features

- Email + password login with rate limiting and account lockout.
- JWT access + refresh token issuance, rotation, and reuse detection.
- Admin-invited registration via single-use email tokens.
- Password reset flow.
- Logout (single-device + global).
- RBAC: seed roles (`super_admin`, `org_admin`, `branch_manager`, `cashier`, `viewer`), permissions on every protected endpoint.
- Branch-scoped access for non-admin users.
- Audit logging of every auth event.

### Backlog Coverage

`VM-AUTH-01` → `VM-AUTH-05`, `VM-AUTH-07`, `VM-AUTH-08`, `VM-ORG-05`

### Dependencies

- v0.2 (entity layer, EventBus, repositories).

### Testing Goals

- 100% of protected endpoints declare and check a permission.
- Cross-tenant access tests return 403 / empty result sets.
- Token rotation, expiry, and revocation covered by integration tests.
- Security tests for OWASP A01 (Broken Access Control) and A07 (Identification Failures).

### Deployment Goals

- Production refuses to start with default `SECRET_KEY` or `DEBUG=true`.
- Auth-related rate limits enforced at the Nginx layer.

### Expected Deliverables

- Tagged release `v0.3.0`.
- `docs/13_AUTHENTICATION.md` and `docs/14_PERMISSION.md` finalised.
- Postman / Bruno collection for the auth surface.

---

# v0.4 — Product Management

> Give catalog managers full control over the product master so later sales and inventory work has something to operate on.

### Objectives

- Deliver catalog CRUD with the performance characteristics required by POS and AI lookups.

### Features

- Category tree CRUD with drag-and-drop ordering and cycle detection.
- Product CRUD (SKU, barcode, price, currency, attributes).
- Product image upload to MinIO with signed read URLs.
- Indexed product search (name, SKU, barcode) returning in ≤ 100 ms.
- CSV / XLSX bulk import / export (background job).

### Backlog Coverage

`VM-CAT-01` → `VM-CAT-05`

### Dependencies

- v0.3 (RBAC), v0.2 (Celery for bulk import).

### Testing Goals

- Bulk import dry-run reports row-level errors without writing.
- Catalog search benchmarked against a 50k-product dataset.
- Permission tests for `catalog.*` actions.

### Deployment Goals

- Image upload survives a backend restart (object storage is durable).

### Expected Deliverables

- Tagged release `v0.4.0`.
- Catalog UI module in the frontend.
- Sample CSV import template under `scripts/samples/`.

---

# v0.5 — Inventory

> Track stock per branch with reservation semantics strong enough to support smart-cart scenarios in v0.8.

### Objectives

- Implement reliable, race-free stock movements and reservations.

### Features

- Per-product per-branch stock view (on-hand, reserved, available).
- Stock-in / stock-out / inter-branch transfer with reason codes and full audit trail.
- Reservation on cart creation, commit on order paid, release on cart expiry.
- Low-stock alerts via the Notification Center.

### Backlog Coverage

`VM-INV-01` → `VM-INV-04`, `VM-NOTIF-01` (in-app inbox prerequisite)

### Dependencies

- v0.4 (products), v0.2 (persistence + EventBus).

### Testing Goals

- Concurrency tests prove no over-selling under load.
- Stock movements reconcile to zero variance in a synthetic month-long simulation.
- Low-stock alert latency ≤ 60 s from threshold breach.

### Deployment Goals

- Reservation TTL configurable via `Settings`.

### Expected Deliverables

- Tagged release `v0.5.0`.
- Inventory UI in the frontend.
- Notification Center MVP (in-app inbox).

---

# v0.6 — Camera Management

> Bring physical cameras into the system as first-class, monitorable resources.

### Objectives

- Make camera onboarding fast, observable, and self-diagnosing.

### Features

- Camera CRUD (name, code, stream URL, location, branch).
- "Test connection" action that fetches one frame and shows a thumbnail.
- Health monitoring: online/offline state, `last_seen_at`, offline alerts.
- Camera grouping by zone (entrance, checkout, aisles).
- Per-camera AI configuration toggles (which pipelines run).

### Backlog Coverage

`VM-CAM-01` → `VM-CAM-05`

### Dependencies

- v0.3 (RBAC, branch scoping).

### Testing Goals

- RTSP / RTMP / HTTP source schemes all covered.
- Offline transitions detected within 60 s.
- Permission tests for `camera.*` actions.

### Deployment Goals

- Camera state survives backend restarts (no in-memory only state).

### Expected Deliverables

- Tagged release `v0.6.0`.
- Camera UI in the frontend with live status indicators.
- `docs/21_CAMERA_MANAGER.md` finalised.

---

# v0.7 — AI Detection

> Stand up the AI Engine and the foundational vision pipelines that every smart-retail feature depends on.

### Objectives

- Deliver a separable AI Engine with reliable detection + tracking + an event stream.

### Features

- AI Engine service skeleton (versioned HTTP / gRPC interface).
- Frame ingestion with auto-reconnect and bounded backpressure.
- YOLOv8 person + object detection.
- ByteTrack multi-object tracking with stable IDs across short occlusions.
- Detection event publication on the EventBus + WebSocket pass-through.
- Model registry (active model is recorded with hash and metadata).
- ONNX Runtime backends: CPU, CUDA, TensorRT, selectable via config.

### Backlog Coverage

`VM-AI-CORE-01` → `VM-AI-CORE-06`, `VM-WS-01`, `VM-WS-02`

### Dependencies

- v0.6 (cameras), v0.2 (EventBus).

### Testing Goals

- mAP and ID-switch rate measured on a held-out test set; results published.
- End-to-end latency (frame in → event out) measured and tracked in metrics.
- Soak test: 24 h continuous run on 4 simulated streams without crash or leak.

### Deployment Goals

- AI Engine runs on either a GPU host (CUDA / TensorRT) or a CPU host (ONNX).
- Resource limits documented per backend.

### Expected Deliverables

- Tagged release `v0.7.0`.
- `docs/22_VIDEO_PIPELINE.md`, `docs/23_OBJECT_DETECTION.md`, `docs/24_OBJECT_TRACKING.md` finalised.
- Public benchmark report under `docs/benchmarks/`.

---

# v0.8 — Smart Cart

> Convert raw detections into a usable smart-checkout experience.

### Objectives

- Ship the headline AI feature: automatic cart updates as shoppers pick up products.

### Features

- Per-tenant product recogniser registration and activation.
- Real-time "product picked up" event emission with confidence scores.
- AI-assisted shopping cart that auto-adds high-confidence items and queues low-confidence ones for cashier confirmation.
- Human-review queue with feedback loop into training labels.
- In-store person tracking (re-identification within a single branch).
- Reservation integration: every auto-added item reserves stock.

### Backlog Coverage

`VM-AI-PROD-01` → `VM-AI-PROD-03`, `VM-AI-CUST-01`, `VM-SALES-01`, `VM-SALES-08`, `VM-SALES-02`, `VM-SALES-03`

### Dependencies

- v0.5 (inventory reservations), v0.7 (detection + tracking).

### Testing Goals

- End-to-end latency from pickup to cart update ≤ 1.5 s.
- Precision ≥ documented baseline on the recognition eval set.
- Stock reservation correctness verified under concurrent shoppers.

### Deployment Goals

- Recogniser model is hot-swappable without dropping streams.
- Smart-cart feature is gated by a per-organization feature flag.

### Expected Deliverables

- Tagged release `v0.8.0`.
- `docs/25_PRODUCT_RECOGNITION.md` and `docs/26_CART_ENGINE.md` finalised.
- A reference checkout-station UI in the frontend.

---

# v0.9 — Dashboard

> Surface live operational state in a single, fast, role-aware UI.

### Objectives

- Give branch managers a real-time pane of glass and a starting point for analytics.

### Features

- Manager landing dashboard: today's revenue, orders, footfall (basic), active alerts.
- Live operations panel: camera tiles, queue length, ongoing alerts (WebSocket-driven).
- Live browser camera view (HLS / WebRTC) with permission checks.
- Notification push channel over WebSocket.
- Customisable widget layout (per-user persistence).

### Backlog Coverage

`VM-DASH-01` → `VM-DASH-03`, `VM-STREAM-01`, `VM-WS-03`, `VM-AI-QUEUE-01`

### Dependencies

- v0.5 (orders/inventory data), v0.7 (live detections), v0.6 (cameras).

### Testing Goals

- Dashboard initial load ≤ 2 s on broadband against a seeded dataset.
- WebSocket push latency ≤ 500 ms inside the LAN.
- Cross-browser smoke tests (Chrome, Edge, Firefox, Safari).

### Deployment Goals

- WebSocket gateway scales independently of REST API workers.

### Expected Deliverables

- Tagged release `v0.9.0`.
- Dashboard UI module in the frontend.
- `docs/37_DASHBOARD.md` finalised.

---

# v1.0 — MVP (Production Launch)

> First production-ready release. Everything required to run a single store, end-to-end, in a real customer environment.

### Objectives

- Cut the first GA release of VisionMart.
- Harden security, observability, and operability for a production tenant.
- Publish all public-facing documentation.

### Features

- Full integration testing across all v0.1–v0.9 features.
- Refunds and discounts on top of v0.8 sales (`VM-SALES-05`, `VM-SALES-06`).
- Receipt printing / emailing (`VM-SALES-07`).
- Email channel for notifications (`VM-NOTIF-02`); user notification preferences (`VM-NOTIF-04`).
- Full REST API contract: versioning (`/api/v1`), OpenAPI + Swagger UI, consistent error model, pagination/filter/sort standard, rate limits, idempotency keys (`VM-API-01` → `VM-API-06`).
- Audit log surfaced in the admin UI.
- Prometheus metrics + a starter Grafana dashboard (`VM-INFRA-10`).
- Privacy & consent management for customers (`VM-CUST-03`).

### Backlog Coverage

All `P0` stories not yet shipped, plus the listed `P1` items above.

### Dependencies

- v0.1 through v0.9.

### Testing Goals

- End-to-end regression suite green across all feature areas.
- Load test: sustained 50 RPS on the API and 16 simultaneous camera streams at target FPS.
- Security review: OWASP Top 10 walkthrough + dependency vulnerability scan with no `Critical` / `High` findings.
- A documented manual UAT script signed off by the product owner.

### Deployment Goals

- Single-node Docker Compose deployment on a customer VM with TLS, backups, and log shipping.
- Zero-downtime rolling restart of stateless services.
- Documented backup + restore procedure (`VM-CLOUD-04`).

### Expected Deliverables

- Tagged release `v1.0.0` — **General Availability**.
- Release notes (`docs/45_RELEASE_NOTE.md` updated).
- Operator runbook (deploy, upgrade, backup, restore, rollback).
- Public OpenAPI spec hosted at `/api/v1/docs`.
- Published SLA / SLO definitions.

---

# v1.1 — Analytics

> Turn the operational data accumulated in v1.0 into business insight.

### Objectives

- Deliver the analytics and reporting features that justify investment in the platform.

### Features

- Heatmap & footfall analytics (`VM-AI-HEAT-01` → `VM-AI-HEAT-03`).
- Customer analytics: footfall summaries, conversion rate, frequency segments (`VM-AN-CUST-01` → `VM-AN-CUST-03`).
- Staff analytics: attendance, checkout productivity, coverage vs footfall (`VM-AN-STAFF-01` → `VM-AN-STAFF-03`).
- Sales and inventory reports with PDF / XLSX export and scheduled delivery (`VM-RPT-01` → `VM-RPT-04`).
- Optional consented face recognition (`VM-AI-CUST-02`) and anonymised demographics (`VM-AI-CUST-03`).
- Shelf occupancy + restock workflow (`VM-AI-INV-01` → `VM-AI-INV-03`).
- Queue SLA alerting (`VM-AI-QUEUE-02`).
- Loss-prevention workflow MVP (`VM-AI-LOSS-01`, `VM-AI-LOSS-02`).

### Backlog Coverage

`AN-CUST`, `AN-STAFF`, `RPT`, `AI-HEAT`, `AI-INV`, `AI-LOSS`, the remaining `AI-QUEUE` and `AI-CUST` items.

### Dependencies

- v1.0.

### Testing Goals

- Analytics accuracy validated against manually counted samples on at least one branch.
- Report numbers reconcile with order data to the cent.
- Background-job throughput verified for scheduled reports at 10× current load.

### Deployment Goals

- Long-running aggregation jobs run on dedicated Celery queues with their own concurrency settings.
- Report exports stored in MinIO with signed download URLs.

### Expected Deliverables

- Tagged release `v1.1.0`.
- Analytics + Reporting UI modules.
- `docs/28_HEATMAP.md`, `docs/29_INVENTORY_AI.md`, `docs/30_QUEUE_DETECTION.md`, `docs/31_THEFT_DETECTION.md`, `docs/32_CUSTOMER_ANALYTICS.md`, `docs/33_STAFF_ANALYTICS.md`, `docs/38_REPORTING.md` finalised.

---

# v1.2 — Multi-Branch

> Make every feature shipped so far behave correctly when a single organization runs many branches under one management plane.

### Objectives

- Eliminate single-branch assumptions throughout the product.
- Add cross-branch operations the field has been asking for.

### Features

- Branch selector in every screen with sticky scope.
- Cross-branch dashboards and reports (compare branches; group by region).
- Inter-branch inventory transfers with in-transit tracking (extends `VM-INV-02`).
- Branch-level KPIs and SLAs.
- Stocktake / physical count workflow (`VM-INV-05`).
- Webhook channel for integrations (`VM-NOTIF-03`).
- API key issuance for service accounts (`VM-AUTH-09`).
- TOTP-based 2FA (`VM-AUTH-06`).
- Customer search and merge (`VM-CUST-02`); link recognised face to profile (`VM-CUST-04`).
- Per-organization branding and settings (`VM-ORG-03`, `VM-ORG-04`).

### Backlog Coverage

Multi-branch hardening across all epics + the listed P2 items.

### Dependencies

- v1.0 (with v1.1 recommended for analytics).

### Testing Goals

- Cross-branch access tests confirm strict branch scoping.
- Performance tests with 10+ branches and 100+ cameras per tenant.
- Webhook delivery resilience tested under broker outages.

### Deployment Goals

- One management plane can serve multiple branches behind a single domain.
- Per-branch feature flags supported.

### Expected Deliverables

- Tagged release `v1.2.0`.
- `docs/35_MULTI_CAMERA.md` and `docs/36_MULTI_BRANCH.md` finalised.
- Updated permission matrix.

---

# v1.3 — Cloud

> Make VisionMart deployable, observable, and scalable on managed cloud platforms.

### Objectives

- Move from "runs on a VM" to "runs on Kubernetes with HA and autoscaling."
- Formalise the disaster-recovery story.

### Features

- Stateless backend, externalised state (`VM-CLOUD-01`).
- Helm chart / Kustomize overlays for Kubernetes (`VM-CLOUD-02`).
- Auto-scaling: HPA for backend, KEDA (or equivalent) for AI workers (`VM-CLOUD-03`).
- Automated nightly backups for Postgres + MinIO with documented restore drills (`VM-CLOUD-04`).
- Multi-region / edge topology reference (`VM-CLOUD-05`).
- Optional managed services: RDS / Cloud SQL for Postgres, ElastiCache / Memorystore for Redis, S3 / GCS for object storage.
- Production-grade observability stack: Prometheus + Grafana + Loki + Tempo (or vendor equivalents).
- TLS via cert-manager; secrets via Sealed Secrets / External Secrets.

### Backlog Coverage

All `CLOUD` stories.

### Dependencies

- v1.0 (with v1.2 strongly recommended for multi-tenant clarity).

### Testing Goals

- Chaos test: kill any single pod / node and confirm zero user-visible impact.
- Restore drill: full database + object-storage restore in under 1 hour, signed off.
- Load test: linear scaling demonstrated up to N×base capacity.

### Deployment Goals

- One-command production deploy to a Kubernetes cluster via the official chart.
- Blue/green or canary deploys supported.

### Expected Deliverables

- Tagged release `v1.3.0`.
- Helm chart published.
- Reference Terraform modules for AWS / GCP / Azure.
- `docs/07_DEPLOYMENT_PLAN.md`, `docs/41_DEPLOYMENT_GPU.md`, `docs/42_CLOUD_SCALING.md`, `docs/43_BACKUP_RECOVERY.md` finalised.

---

# v2.0 — Enterprise

> Round VisionMart out as an enterprise platform: integrations, mobile, IoT, advanced AI, and the SaaS-grade controls large customers require.

### Objectives

- Make VisionMart a credible choice for retail chains and franchises.
- Open the platform to a broader ecosystem (mobile, IoT, third-party integrations).

### Features

- Payment gateway integrations (VNPay, Stripe, etc.) (`VM-SALES-04`).
- Mobile apps:
  - Manager mobile dashboard with push notifications (`VM-MOB-01`, `VM-MOB-02`).
  - Mobile clerk app for scan / restock / stocktake (`VM-MOB-03`).
  - Customer companion app (`VM-MOB-04`).
- IoT integration over MQTT for door sensors, scales, weight sensors (`VM-MQTT-01`, `VM-MQTT-02`).
- SSO / SAML / OIDC for enterprise identity providers.
- Advanced loss prevention with model-assisted rule tuning.
- Per-tenant data residency controls and audit-grade export.
- Marketplace of optional AI modules (face recognition, demographics, etc.) with explicit per-tenant enablement.
- Long-term retention tier (cold storage for video clips and detections).
- Customer support portal with in-app diagnostics bundling.

### Backlog Coverage

All `MOB`, all `MQTT`, remaining `SALES` and `NOTIF` items, and net-new enterprise features tracked in a future v2 epic.

### Dependencies

- v1.1, v1.2, v1.3.

### Testing Goals

- Enterprise penetration test by an external party with all `High`/`Critical` findings remediated.
- Multi-region failover drill executed end-to-end.
- Mobile-app stores submission requirements (App Store, Play Store) passed.
- 99.9% uptime measured on the reference production tenant over a rolling 90-day window prior to release.

### Deployment Goals

- Multi-region production deployment with active/active reads and active/passive writes.
- Per-tenant data residency enforcement validated.
- App-store releases for iOS and Android.

### Expected Deliverables

- Tagged release `v2.0.0` — **Enterprise Edition**.
- Published mobile apps on App Store and Play Store.
- Enterprise security whitepaper (architecture, data flow, controls).
- Integration guide for SSO providers.
- Updated `docs/45_RELEASE_NOTE.md` with the full v1 → v2 changelog.

---

## Cross-Release Engineering Tracks

Some work runs in parallel with the release plan and contributes a slice into every release:

| Track | What it delivers each release |
|-------|--------------------------------|
| **Security** | Dependency scanning, secret-rotation drills, threat-modelling reviews. |
| **Observability** | Metrics, logs, traces, and dashboards for every new feature. |
| **Documentation** | Every new feature ships with updates to the relevant `docs/NN_*.md`. |
| **Performance** | Benchmarks and SLO budgets updated whenever a hot path changes. |
| **Developer Experience** | CLI helpers, scripts, fixtures, and contributor docs. |

---

## Out of Scope (for now)

The following are intentionally *not* on the roadmap until there is a clear customer signal:

- Public marketplace for third-party AI models.
- Built-in eCommerce storefront.
- Native voice-of-customer / NPS surveys.
- Hardware certification programme.

---

*This roadmap is a living document. Releases will be re-scoped, split, or accelerated as we learn from real deployments. Changes to release scope must update this file and link to the originating decision (PR, ADR, or sprint review).*
