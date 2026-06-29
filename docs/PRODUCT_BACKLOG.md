# VisionMart — Product Backlog

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/PRODUCT_BACKLOG.md`
> **Owner:** Product Owner
> **Audience:** Scrum Team (Backend, Frontend, AI, DevOps, QA)
> **Status:** v1.0 — Initial backlog

---

## Conventions

- **Priority:** `P0` Critical · `P1` High · `P2` Medium · `P3` Low · `P4` Nice-to-have
- **Complexity (story points, Fibonacci):** `1`, `2`, `3`, `5`, `8`, `13`, `21`
  - `13` and `21` are *epic-sized* and should be split before being pulled into a sprint.
- **Story ID:** `VM-<EPIC>-<NN>` (e.g. `VM-AUTH-03`)
- **Dependencies:** Listed by Story ID. `—` means no upstream dependency.
- **INVEST:** Every story is Independent, Negotiable, Valuable, Estimable, Small, Testable.

---

## Epic Map

| # | Epic | Code | Goal |
|---|------|------|------|
| 1 | Platform Foundation & DevOps | `INFRA` | Containerised, observable, deployable platform. |
| 2 | Authentication & Authorization | `AUTH` | Secure identity, sessions, and RBAC. |
| 3 | Multi-Tenancy & Organization | `ORG` | Organizations, branches, and per-tenant isolation. |
| 4 | Employee Management | `EMP` | Staff lifecycle, roles, and assignment to branches. |
| 5 | Customer Management | `CUST` | Customer profiles, recognition links, and consent. |
| 6 | Catalog Management | `CAT` | Products, categories, pricing. |
| 7 | Inventory Management | `INV` | Stock levels, reservations, low-stock alerts. |
| 8 | Sales — Shopping Cart, Orders & Payment | `SALES` | End-to-end checkout, including AI-assisted carts. |
| 9 | Camera Management | `CAM` | Device registry, health, configuration. |
| 10 | Live Video Streaming | `STREAM` | Real-time browser viewing of camera feeds. |
| 11 | AI — Object Detection & Tracking | `AI-CORE` | Foundational detection + multi-object tracking pipeline. |
| 12 | AI — Product Recognition & Smart Cart | `AI-PROD` | Recognising products picked up by a shopper. |
| 13 | AI — Customer Tracking & Re-Identification | `AI-CUST` | Per-shopper journey across cameras (privacy-aware). |
| 14 | AI — Inventory Vision | `AI-INV` | Shelf occupancy, gap detection, restock alerts. |
| 15 | AI — Heatmap & Footfall | `AI-HEAT` | Aggregated movement and dwell analytics. |
| 16 | AI — Queue Detection | `AI-QUEUE` | Queue length and wait-time alerting. |
| 17 | AI — Loss Prevention / Theft Detection | `AI-LOSS` | Suspicious-behaviour alerts. |
| 18 | Customer Analytics | `AN-CUST` | Demographics, frequency, conversion. |
| 19 | Staff Analytics | `AN-STAFF` | Coverage, productivity, attendance. |
| 20 | Dashboard | `DASH` | Live operational view for managers. |
| 21 | Reporting & Export | `RPT` | Scheduled, exportable business reports. |
| 22 | Notification Center | `NOTIF` | Multi-channel alert delivery and inbox. |
| 23 | Public REST API | `API` | Versioned, documented, rate-limited API surface. |
| 24 | Real-time — WebSocket | `WS` | Browser-pushed live events. |
| 25 | IoT — MQTT Integration | `MQTT` | Edge devices and sensors. |
| 26 | Cloud Deployment & Scalability | `CLOUD` | Horizontal scaling, HA, disaster recovery. |
| 27 | Mobile App (Future) | `MOB` | iOS/Android companion app. |

---

# Epic 1 — Platform Foundation & DevOps (`INFRA`)

> Establish the deployable, observable backbone that every other epic depends on.

### `VM-INFRA-01` — Containerised local stack

- **Description:** As a developer, I can run the full VisionMart stack (Postgres, Redis, MinIO, Backend, AI Engine, Frontend, Nginx) with a single `docker compose up`.
- **Business Value:** Reduces onboarding time from days to under an hour; guarantees parity between dev and prod.
- **Acceptance Criteria:**
  - `docker compose up -d` brings the stack to a `healthy` state.
  - Each service exposes a healthcheck used by Compose.
  - No service requires manual host configuration after `cp .env.example .env`.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** —

### `VM-INFRA-02` — Centralised configuration via environment

- **Description:** As an operator, I can change any tunable value (URLs, secrets, pool sizes, feature flags) via `.env` without editing source.
- **Business Value:** Enables safe rotation of secrets and environment-specific overrides.
- **Acceptance Criteria:**
  - No hardcoded secrets, ports, or URLs in source code.
  - `.env.example` documents every variable.
  - Production refuses to start when secrets are left at defaults.
- **Priority:** P0 · **Complexity:** 3 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-03` — Structured logging with request correlation

- **Description:** As an SRE, I can trace any HTTP request across services using a correlation ID present in every log line.
- **Business Value:** Cuts incident MTTR by enabling fast log correlation.
- **Acceptance Criteria:**
  - JSON logs in production, human-readable in dev.
  - `X-Request-ID` is generated when absent and echoed in the response.
  - The ID appears in every log line emitted while processing the request.
- **Priority:** P0 · **Complexity:** 3 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-04` — Liveness and readiness endpoints

- **Description:** As a platform engineer, I can probe each service for liveness and readiness independently.
- **Business Value:** Enables zero-downtime deploys on Docker / Kubernetes.
- **Acceptance Criteria:**
  - `/health` returns 200 with no external dependency.
  - `/ready` returns 503 when DB / Redis are unreachable.
- **Priority:** P0 · **Complexity:** 2 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-05` — CI pipeline (lint, type-check, test, build)

- **Description:** As a maintainer, every pull request runs lint, type-check, unit tests, and image builds automatically.
- **Business Value:** Prevents regressions and enforces quality bar.
- **Acceptance Criteria:**
  - Pipeline runs on every PR and on `main`.
  - Backend, AI engine, and frontend each have their own job.
  - Failing checks block merge.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-06` — Database migration tooling

- **Description:** As a backend developer, I can generate and apply schema migrations with one command.
- **Business Value:** Safe, reversible schema evolution in every environment.
- **Acceptance Criteria:**
  - Alembic generates and applies migrations.
  - Migrations run automatically during deploy.
  - A rollback procedure is documented.
- **Priority:** P0 · **Complexity:** 3 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-07` — Background job runner

- **Description:** As a developer, I can enqueue async work (reports, exports, AI batch jobs) to a Celery worker.
- **Business Value:** Keeps the API responsive; enables scheduled jobs.
- **Acceptance Criteria:**
  - Celery worker connects to Redis broker and result backend.
  - Tasks are retried with exponential backoff on transient errors.
  - Failed tasks are visible in logs with full traceback.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-08` — Reverse proxy with security headers and rate limiting

- **Description:** As a security engineer, all public traffic terminates at Nginx with TLS, HSTS, CSP, and per-route rate limits.
- **Business Value:** Reduces attack surface against OWASP Top 10.
- **Acceptance Criteria:**
  - HTTPS-only with HSTS preload.
  - Security headers present on every response.
  - Auth endpoints have stricter rate limits than read APIs.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-09` — Object storage for frames and media

- **Description:** As a developer, I can store and retrieve binary artefacts (frames, snapshots, exports) via an S3-compatible interface.
- **Business Value:** Decouples large objects from the OLTP database.
- **Acceptance Criteria:**
  - MinIO is provisioned with default buckets.
  - Backend and AI engine read credentials from env.
  - Bucket policies are least-privilege.
- **Priority:** P1 · **Complexity:** 3 · **Dependencies:** `VM-INFRA-01`

### `VM-INFRA-10` — Metrics and monitoring baseline

- **Description:** As an SRE, I can scrape Prometheus-compatible metrics from each service.
- **Business Value:** Enables SLO-based alerting and capacity planning.
- **Acceptance Criteria:**
  - `/metrics` endpoint exposed on backend and AI engine.
  - Standard process and HTTP metrics emitted.
  - A starter Grafana dashboard is included.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-INFRA-04`

---

# Epic 2 — Authentication & Authorization (`AUTH`)

### `VM-AUTH-01` — Email + password registration (admin-invited)

- **Description:** As an organization admin, I can invite a user by email; the invitee sets their own password on first login.
- **Business Value:** Controls who joins the tenant.
- **Acceptance Criteria:**
  - Invite link is single-use and expires in 72 hours.
  - Passwords meet a documented strength policy.
  - Invalid / expired tokens return a clear error.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-ORG-01`, `VM-NOTIF-02`

### `VM-AUTH-02` — Login with email and password

- **Description:** As a user, I can log in with email and password and receive a session token.
- **Business Value:** Baseline access control.
- **Acceptance Criteria:**
  - Failed logins are rate-limited per IP and per account.
  - Lockout after N consecutive failures with audited unlock path.
  - Successful login emits an `auth.login.succeeded` event.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-AUTH-01`

### `VM-AUTH-03` — JWT access + refresh tokens

- **Description:** As a client, I receive short-lived access tokens and longer-lived refresh tokens that can be rotated.
- **Business Value:** Industry-standard stateless auth, friendly to mobile and SPA.
- **Acceptance Criteria:**
  - Access token TTL ≤ 15 min, refresh ≤ 14 days, both configurable.
  - Refresh rotation invalidates the previous token (token reuse detection).
  - Tokens are signed with a key sourced from the secret manager.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-AUTH-02`

### `VM-AUTH-04` — Logout and global session revocation

- **Description:** As a user, I can log out of one device or revoke all my active sessions.
- **Business Value:** Reduces blast radius of stolen credentials.
- **Acceptance Criteria:**
  - Revoked refresh tokens cannot be reused.
  - Admin can force-revoke any user's sessions.
  - Revocation is reflected within 60 seconds across all instances.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-AUTH-03`

### `VM-AUTH-05` — Password reset flow

- **Description:** As a user who forgot my password, I can request a reset link delivered by email.
- **Business Value:** Self-service recovery; cuts support load.
- **Acceptance Criteria:**
  - Reset tokens are single-use and expire in 30 min.
  - The flow does not reveal whether an email exists.
  - On reset, all active sessions for the user are revoked.
- **Priority:** P1 · **Complexity:** 3 · **Dependencies:** `VM-AUTH-03`, `VM-NOTIF-02`

### `VM-AUTH-06` — Multi-factor authentication (TOTP)

- **Description:** As a security-conscious user, I can enable TOTP-based 2FA on my account.
- **Business Value:** Mitigates credential theft.
- **Acceptance Criteria:**
  - User can enrol via QR code and back-up codes.
  - Login requires the TOTP code when enabled.
  - Admins can require 2FA for selected roles.
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-AUTH-02`

### `VM-AUTH-07` — Role-Based Access Control (RBAC)

- **Description:** As an admin, I can assign roles to users; each role bundles permissions; permissions gate API actions.
- **Business Value:** Scalable, auditable authorization.
- **Acceptance Criteria:**
  - System ships with seed roles: `super_admin`, `org_admin`, `branch_manager`, `cashier`, `viewer`.
  - Custom roles can be created and edited.
  - Every protected endpoint declares a required permission.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** `VM-AUTH-03`

### `VM-AUTH-08` — Branch-scoped access

- **Description:** As an org admin, I can limit a user to one or more branches.
- **Business Value:** Enforces least-privilege for branch staff.
- **Acceptance Criteria:**
  - Users only see data for branches they belong to.
  - Cross-branch access is denied with a 403 and audited.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-AUTH-07`, `VM-ORG-02`

### `VM-AUTH-09` — API key issuance for service accounts

- **Description:** As an integrator, I can mint scoped API keys for server-to-server calls.
- **Business Value:** Enables third-party integrations without sharing user credentials.
- **Acceptance Criteria:**
  - Keys are scoped to permissions and optionally to IP ranges.
  - Keys can be rotated and revoked.
  - Usage of each key is logged.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-AUTH-07`

---

# Epic 3 — Multi-Tenancy & Organization (`ORG`)

### `VM-ORG-01` — Create an organization (tenant)

- **Description:** As a super-admin, I can create a new organization with a unique slug and an initial admin user.
- **Business Value:** Foundation of multi-tenant isolation.
- **Acceptance Criteria:**
  - Slug is URL-safe and unique.
  - Creating an organization auto-creates default roles and settings.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** —

### `VM-ORG-02` — Manage branches under an organization

- **Description:** As an org admin, I can add, edit, deactivate, and list branches.
- **Business Value:** Models physical store locations.
- **Acceptance Criteria:**
  - Branches have a code unique within the organization.
  - Deactivating a branch hides it from operational dashboards.
  - Deactivation does not delete historical data.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-ORG-01`

### `VM-ORG-03` — Per-organization branding and settings

- **Description:** As an org admin, I can upload a logo, set the default timezone, currency, and language.
- **Business Value:** White-label experience.
- **Acceptance Criteria:**
  - Settings are scoped to the organization.
  - The UI reflects the chosen currency and timezone.
- **Priority:** P2 · **Complexity:** 3 · **Dependencies:** `VM-ORG-01`

### `VM-ORG-04` — Global and per-tenant system settings

- **Description:** As a platform admin, I can set defaults that an organization may override.
- **Business Value:** Flexible product configuration.
- **Acceptance Criteria:**
  - Lookup order: org-specific → global → built-in default.
  - Setting changes are audited.
- **Priority:** P2 · **Complexity:** 3 · **Dependencies:** `VM-ORG-01`

### `VM-ORG-05` — Tenant data isolation guarantees

- **Description:** As a security reviewer, I can prove that no query returns rows from another tenant.
- **Business Value:** Hard requirement for multi-tenant SaaS.
- **Acceptance Criteria:**
  - All tenant-scoped queries include `organization_id` in the predicate.
  - A test suite attempts cross-tenant access and expects 403/empty.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** `VM-ORG-01`, `VM-AUTH-07`

---

# Epic 4 — Employee Management (`EMP`)

### `VM-EMP-01` — Create and edit employee records

- **Description:** As an HR-capable user, I can create an employee with name, code, position, and branch assignment.
- **Business Value:** Source of truth for staffing data.
- **Acceptance Criteria:**
  - Employee code is unique within an organization.
  - Required fields are validated server-side.
- **Priority:** P1 · **Complexity:** 3 · **Dependencies:** `VM-ORG-02`

### `VM-EMP-02` — Link an employee to a system user

- **Description:** As an admin, I can link an employee record to a user account so the same person can log in and be tracked operationally.
- **Business Value:** One identity across HR and ops.
- **Acceptance Criteria:**
  - One user maps to at most one employee.
  - Unlinking does not delete either record.
- **Priority:** P1 · **Complexity:** 2 · **Dependencies:** `VM-EMP-01`, `VM-AUTH-01`

### `VM-EMP-03` — Employee lifecycle (hire / terminate)

- **Description:** As an HR user, I can record hire and termination dates; terminated employees are hidden from rosters.
- **Business Value:** Accurate workforce reporting.
- **Acceptance Criteria:**
  - Termination revokes the linked user's access.
  - Historical records remain queryable for reports.
- **Priority:** P2 · **Complexity:** 3 · **Dependencies:** `VM-EMP-01`

### `VM-EMP-04` — Employee directory and search

- **Description:** As a manager, I can search and filter employees by name, branch, position, or status.
- **Business Value:** Operational efficiency.
- **Acceptance Criteria:**
  - Paginated, sortable, filterable list.
  - Search is indexed and returns within 300 ms for 10k rows.
- **Priority:** P2 · **Complexity:** 3 · **Dependencies:** `VM-EMP-01`

---

# Epic 5 — Customer Management (`CUST`)

### `VM-CUST-01` — Manage customer profiles

- **Description:** As a staff user, I can create and edit customer profiles (optional name, email, phone, attributes).
- **Business Value:** Enables loyalty and analytics.
- **Acceptance Criteria:**
  - All PII fields are optional to support anonymous shoppers.
  - Email and phone, when present, are validated.
- **Priority:** P1 · **Complexity:** 3 · **Dependencies:** `VM-ORG-02`

### `VM-CUST-02` — Customer search and merge

- **Description:** As a staff user, I can search customers and merge duplicates.
- **Business Value:** Clean data for analytics and loyalty.
- **Acceptance Criteria:**
  - Merge migrates orders, carts, and recognition links to the survivor.
  - Merge is auditable and reversible within 30 days.
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-CUST-01`

### `VM-CUST-03` — Privacy & consent management

- **Description:** As a customer, my biometric data is only retained when I have given explicit consent.
- **Business Value:** GDPR / CCPA compliance; brand trust.
- **Acceptance Criteria:**
  - Consent state is stored with timestamp and source.
  - Withdrawing consent deletes face embeddings within 24 hours.
  - A data-export request returns all data for the customer.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** `VM-CUST-01`

### `VM-CUST-04` — Link recognised face to a customer profile

- **Description:** As a staff user, I can review unidentified high-confidence faces and link them to an existing customer.
- **Business Value:** Builds the recognition dataset over time.
- **Acceptance Criteria:**
  - Only users with the `customer.link_face` permission can do this.
  - Each link is audited.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-CUST-01`, `VM-AI-CUST-02`

---

# Epic 6 — Catalog Management (`CAT`)

### `VM-CAT-01` — Manage categories as a tree

- **Description:** As a catalog manager, I can build a hierarchical category tree.
- **Business Value:** Enables navigation, reporting, and recommendation grouping.
- **Acceptance Criteria:**
  - Drag-and-drop reordering supported.
  - Cycles are rejected.
  - Deleting a category requires reassigning its products.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-ORG-02`

### `VM-CAT-02` — CRUD products with SKU, barcode, price

- **Description:** As a catalog manager, I can create and edit products with SKU, barcode, name, price, currency, and attributes.
- **Business Value:** Sellable inventory definition.
- **Acceptance Criteria:**
  - SKU unique per organization; barcode optional.
  - Price stored to 4 decimal places.
  - Currency defaults to organization default.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-ORG-01`

### `VM-CAT-03` — Product images & media

- **Description:** As a catalog manager, I can attach one primary image and multiple gallery images to a product.
- **Business Value:** Visual catalog for POS, analytics, and AI training.
- **Acceptance Criteria:**
  - Images stored in MinIO with signed read URLs.
  - Max file size and allowed mime types are enforced.
- **Priority:** P2 · **Complexity:** 3 · **Dependencies:** `VM-CAT-02`, `VM-INFRA-09`

### `VM-CAT-04` — Bulk import / export products

- **Description:** As a catalog manager, I can import a CSV/XLSX file to create or update products in bulk.
- **Business Value:** Migration from legacy POS systems.
- **Acceptance Criteria:**
  - Dry-run mode reports errors per row without writing.
  - Up to 50k rows handled via background job.
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-CAT-02`, `VM-INFRA-07`

### `VM-CAT-05` — Catalog search

- **Description:** As a cashier or AI module, I can search products by name, SKU, or barcode within 100 ms.
- **Business Value:** Fast POS and inference paths.
- **Acceptance Criteria:**
  - Backed by trigram / full-text index.
  - Returns scored results.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-CAT-02`

---

# Epic 7 — Inventory Management (`INV`)

### `VM-INV-01` — Stock levels per product per branch

- **Description:** As an inventory manager, I can view current on-hand, reserved, and available stock for each product in each branch.
- **Business Value:** Operational visibility.
- **Acceptance Criteria:**
  - Quantities are non-negative.
  - View paginates and is filterable by branch and category.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-CAT-02`, `VM-ORG-02`

### `VM-INV-02` — Stock adjustments (in / out / transfer)

- **Description:** As an inventory manager, I can record stock-in, stock-out, and inter-branch transfers with a reason code.
- **Business Value:** Auditable inventory movements.
- **Acceptance Criteria:**
  - Every movement creates an audit entry.
  - Negative stock is blocked unless `allow_negative_stock` is on.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-INV-01`

### `VM-INV-03` — Reservation on cart, commit on order

- **Description:** As a sales engine, I can reserve stock when an item enters a cart and commit (decrement) when the order is paid.
- **Business Value:** Prevents over-selling.
- **Acceptance Criteria:**
  - Reservations expire when carts expire.
  - Concurrent reservations are serialised correctly.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** `VM-INV-01`, `VM-SALES-01`

### `VM-INV-04` — Low-stock alerts

- **Description:** As an inventory manager, I receive a notification when stock falls below the reorder level.
- **Business Value:** Avoids stockouts.
- **Acceptance Criteria:**
  - Threshold is configurable per product per branch.
  - Alert is delivered via the Notification Center.
- **Priority:** P1 · **Complexity:** 3 · **Dependencies:** `VM-INV-01`, `VM-NOTIF-01`

### `VM-INV-05` — Stocktake / physical count workflow

- **Description:** As an inventory manager, I can run a stocktake session, scan items, and post variances.
- **Business Value:** Reconciliation against physical reality.
- **Acceptance Criteria:**
  - Session captures expected vs counted.
  - Posting variances generates audited adjustments.
- **Priority:** P2 · **Complexity:** 13 · **Dependencies:** `VM-INV-02`

---

# Epic 8 — Sales: Shopping Cart, Orders & Payment (`SALES`)

### `VM-SALES-01` — Create and update a shopping cart

- **Description:** As a cashier or AI source, I can create a cart, add / remove / change items, and view a running total.
- **Business Value:** Foundation of checkout.
- **Acceptance Criteria:**
  - Cart total recalculates on every change.
  - Cart has a configurable expiration.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-CAT-02`, `VM-INV-03`

### `VM-SALES-02` — Convert cart to order

- **Description:** As a cashier, I can confirm a cart, producing an order with a unique code.
- **Business Value:** Records the sale.
- **Acceptance Criteria:**
  - Order is immutable once status reaches `paid`.
  - Order links back to the source cart and recognised customer (if any).
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-SALES-01`

### `VM-SALES-03` — Cash payment

- **Description:** As a cashier, I can record a cash payment, including tendered amount and change due.
- **Business Value:** Supports the most common in-store payment.
- **Acceptance Criteria:**
  - Tendered amount ≥ total.
  - Change is computed and shown.
- **Priority:** P0 · **Complexity:** 3 · **Dependencies:** `VM-SALES-02`

### `VM-SALES-04` — Card / QR payment via gateway

- **Description:** As a cashier, I can collect a card or QR payment through an integrated gateway (e.g. VNPay / Stripe).
- **Business Value:** Cashless checkout.
- **Acceptance Criteria:**
  - Payment intent lifecycle is reflected on the order.
  - Webhook reconciles late confirmations.
  - Reversed payments cancel the order automatically.
- **Priority:** P1 · **Complexity:** 13 · **Dependencies:** `VM-SALES-02`

### `VM-SALES-05` — Refunds and partial refunds

- **Description:** As a manager, I can issue a full or partial refund against a paid order.
- **Business Value:** Customer service and compliance.
- **Acceptance Criteria:**
  - Refund restores stock for refunded items.
  - Refund is auditable and reflected in reports.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-SALES-02`

### `VM-SALES-06` — Discounts and promotions

- **Description:** As a manager, I can configure order- and item-level discount rules (percentage, fixed, BOGO).
- **Business Value:** Marketing flexibility.
- **Acceptance Criteria:**
  - Rules are evaluated deterministically with a documented precedence.
  - Disabled rules never apply.
- **Priority:** P2 · **Complexity:** 13 · **Dependencies:** `VM-SALES-02`

### `VM-SALES-07` — Printable / emailable receipt

- **Description:** As a customer, I can receive a receipt printed or emailed.
- **Business Value:** Standard checkout expectation.
- **Acceptance Criteria:**
  - Receipt template is configurable per organization.
  - Email delivery uses the Notification Center.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-SALES-02`, `VM-NOTIF-02`

### `VM-SALES-08` — AI-assisted cart from camera

- **Description:** As a shopper at a smart checkout, items I pick up are added to my cart automatically.
- **Business Value:** Differentiating, frictionless checkout.
- **Acceptance Criteria:**
  - Items recognised with confidence ≥ threshold are auto-added.
  - Lower-confidence items prompt cashier confirmation.
  - End-to-end latency from pickup to cart ≤ 1.5 s.
- **Priority:** P1 · **Complexity:** 21 · **Dependencies:** `VM-SALES-01`, `VM-AI-PROD-02`, `VM-AI-CUST-01`

---

# Epic 9 — Camera Management (`CAM`)

### `VM-CAM-01` — Register a camera

- **Description:** As a branch manager, I can register a camera by name, code, stream URL, and location.
- **Business Value:** Pre-requisite to any vision feature.
- **Acceptance Criteria:**
  - Camera code is unique per organization.
  - Stream URL is validated for scheme (rtsp / rtmp / http).
- **Priority:** P0 · **Complexity:** 3 · **Dependencies:** `VM-ORG-02`

### `VM-CAM-02` — Test camera connection

- **Description:** As a branch manager, I can trigger a "test" that fetches one frame and reports success / failure.
- **Business Value:** Validates configuration before going live.
- **Acceptance Criteria:**
  - Test result returns within 10 s.
  - On success, a thumbnail is shown.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-CAM-01`, `VM-INFRA-09`

### `VM-CAM-03` — Camera health monitoring

- **Description:** As an operator, I can see online / offline state and `last_seen_at` for every camera.
- **Business Value:** Detects downtime quickly.
- **Acceptance Criteria:**
  - Offline status reflected within 60 s of stream drop.
  - Transition events are audited and notifiable.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-CAM-01`, `VM-NOTIF-01`

### `VM-CAM-04` — Per-camera AI configuration

- **Description:** As an operator, I can choose which AI pipelines (detection, recognition, heatmap) run on a given camera.
- **Business Value:** Cost control; not every camera needs every model.
- **Acceptance Criteria:**
  - Toggles persist and take effect within 30 s.
  - Disabling a pipeline frees its GPU/CPU budget.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-CAM-01`, `VM-AI-CORE-01`

### `VM-CAM-05` — Camera grouping by zone

- **Description:** As a manager, I can group cameras by physical zone (entrance, checkout, aisles) for analytics.
- **Business Value:** Meaningful grouping in dashboards.
- **Acceptance Criteria:**
  - Groups are organization-scoped.
  - A camera belongs to exactly one zone.
- **Priority:** P2 · **Complexity:** 3 · **Dependencies:** `VM-CAM-01`

---

# Epic 10 — Live Video Streaming (`STREAM`)

### `VM-STREAM-01` — Browser live view (HLS / WebRTC)

- **Description:** As an operator, I can watch a live camera feed in the web UI.
- **Business Value:** Real-time supervision.
- **Acceptance Criteria:**
  - End-to-end latency ≤ 3 s.
  - Stream stops when the tab is closed.
  - Access is permission-checked.
- **Priority:** P1 · **Complexity:** 13 · **Dependencies:** `VM-CAM-02`, `VM-AUTH-07`

### `VM-STREAM-02` — Multi-camera grid view

- **Description:** As an operator, I can watch up to 9 camera feeds simultaneously.
- **Business Value:** Surveillance efficiency.
- **Acceptance Criteria:**
  - Adaptive bitrate keeps frames flowing under bandwidth pressure.
  - Selected camera can be enlarged.
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-STREAM-01`

### `VM-STREAM-03` — Snapshot capture

- **Description:** As an operator, I can take a snapshot of the live feed and save it to incidents.
- **Business Value:** Evidence capture.
- **Acceptance Criteria:**
  - Snapshot stored in MinIO with metadata (camera, timestamp, user).
- **Priority:** P2 · **Complexity:** 3 · **Dependencies:** `VM-STREAM-01`, `VM-INFRA-09`

### `VM-STREAM-04` — Short-term clip recording on alert

- **Description:** As an investigator, I can replay a 30-second clip around any alert.
- **Business Value:** Investigation context.
- **Acceptance Criteria:**
  - Clip is retained per retention policy (default 30 days).
  - Clip access is audited.
- **Priority:** P2 · **Complexity:** 13 · **Dependencies:** `VM-STREAM-01`, `VM-INFRA-09`

---

# Epic 11 — AI: Object Detection & Tracking (`AI-CORE`)

### `VM-AI-CORE-01` — AI Engine service skeleton

- **Description:** As an AI developer, I have a separable AI Engine service that receives frames and returns detections.
- **Business Value:** Decouples AI from business backend; enables independent scaling.
- **Acceptance Criteria:**
  - Engine exposes a versioned HTTP / gRPC interface.
  - It can run on CPU, CUDA, or TensorRT backends via config.
- **Priority:** P0 · **Complexity:** 13 · **Dependencies:** `VM-INFRA-01`

### `VM-AI-CORE-02` — Frame ingestion pipeline

- **Description:** As the AI Engine, I can read frames from RTSP / RTMP / file sources at a configurable target FPS.
- **Business Value:** Reliable input layer for every model.
- **Acceptance Criteria:**
  - Source failures auto-reconnect with backoff.
  - Backpressure does not crash the process.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** `VM-AI-CORE-01`, `VM-CAM-01`

### `VM-AI-CORE-03` — YOLOv8 person & object detection

- **Description:** As the AI Engine, I detect people and configured object classes per frame.
- **Business Value:** Building block for every higher-level vision feature.
- **Acceptance Criteria:**
  - mAP ≥ documented benchmark on a held-out test set.
  - Inference latency reported in metrics.
- **Priority:** P0 · **Complexity:** 13 · **Dependencies:** `VM-AI-CORE-02`

### `VM-AI-CORE-04` — ByteTrack multi-object tracking

- **Description:** As the AI Engine, I assign and maintain stable track IDs across frames.
- **Business Value:** Enables counting, dwell, and journey analytics.
- **Acceptance Criteria:**
  - Track ID survives short occlusions (≤ 2 s).
  - ID switches are below a documented threshold on the eval set.
- **Priority:** P0 · **Complexity:** 13 · **Dependencies:** `VM-AI-CORE-03`

### `VM-AI-CORE-05` — Detection events published to the bus

- **Description:** As a downstream module, I subscribe to a stream of detection / track events.
- **Business Value:** Decouples vision from consumers.
- **Acceptance Criteria:**
  - Events include camera, timestamp, track ID, class, confidence, bbox.
  - At-least-once delivery semantics documented.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** `VM-AI-CORE-04`, `VM-WS-01`

### `VM-AI-CORE-06` — Configurable model registry

- **Description:** As an AI ops user, I can switch the active model version without redeploying.
- **Business Value:** Safe model rollout / rollback.
- **Acceptance Criteria:**
  - Active model is recorded with hash and metadata.
  - Switching is reversible and audited.
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-AI-CORE-03`

---

# Epic 12 — AI: Product Recognition & Smart Cart (`AI-PROD`)

### `VM-AI-PROD-01` — Train / register product recogniser

- **Description:** As an AI ops user, I can register a product recognition model for the organization's catalog.
- **Business Value:** Per-tenant accuracy.
- **Acceptance Criteria:**
  - Model registration links to a catalog snapshot.
  - Evaluation report is attached.
- **Priority:** P1 · **Complexity:** 13 · **Dependencies:** `VM-AI-CORE-06`, `VM-CAT-03`

### `VM-AI-PROD-02` — Recognise picked-up products in real time

- **Description:** As the AI Engine, I emit "product picked up" events for items removed from a shelf or placed in a cart.
- **Business Value:** Powers smart carts and shrinkage detection.
- **Acceptance Criteria:**
  - Precision ≥ documented baseline.
  - End-to-end latency ≤ 1 s.
- **Priority:** P1 · **Complexity:** 21 · **Dependencies:** `VM-AI-CORE-04`, `VM-AI-PROD-01`

### `VM-AI-PROD-03` — Confidence-based human review queue

- **Description:** As a cashier, I see a queue of low-confidence recognition events to confirm or correct.
- **Business Value:** Closes the loop and improves the model.
- **Acceptance Criteria:**
  - Confirmations are written back as training labels.
  - Queue has SLA visibility (oldest age).
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-AI-PROD-02`

---

# Epic 13 — AI: Customer Tracking & Re-Identification (`AI-CUST`)

### `VM-AI-CUST-01` — In-store person tracking

- **Description:** As the AI Engine, I maintain a stable per-shopper track across one branch's cameras.
- **Business Value:** Foundation for journey analytics and smart cart.
- **Acceptance Criteria:**
  - Re-ID across cameras under documented conditions.
  - No PII required for tracking.
- **Priority:** P1 · **Complexity:** 21 · **Dependencies:** `VM-AI-CORE-04`

### `VM-AI-CUST-02` — Optional face recognition (consent-gated)

- **Description:** As a staff user with permission, I see recognised returning customers — only when the customer has consented.
- **Business Value:** Personalised service.
- **Acceptance Criteria:**
  - Recognition runs only on consented customers' embeddings.
  - Recognition is gated by `customer.recognise` permission.
- **Priority:** P2 · **Complexity:** 13 · **Dependencies:** `VM-AI-CUST-01`, `VM-CUST-03`

### `VM-AI-CUST-03` — Anonymised demographics (age band, gender)

- **Description:** As an analyst, I see aggregated demographic estimates of footfall.
- **Business Value:** Marketing insight.
- **Acceptance Criteria:**
  - Only aggregates are stored; raw per-person attributes are discarded.
  - Estimates include a confidence band.
- **Priority:** P3 · **Complexity:** 13 · **Dependencies:** `VM-AI-CUST-01`

---

# Epic 14 — AI: Inventory Vision (`AI-INV`)

### `VM-AI-INV-01` — Shelf occupancy detection

- **Description:** As the AI Engine, I estimate occupancy of designated shelf regions.
- **Business Value:** Detects out-of-stock conditions on the floor.
- **Acceptance Criteria:**
  - Per-shelf occupancy emitted at a configurable cadence.
  - Calibration UI provided.
- **Priority:** P2 · **Complexity:** 13 · **Dependencies:** `VM-AI-CORE-03`, `VM-CAM-04`

### `VM-AI-INV-02` — Gap / out-of-stock alerts

- **Description:** As an inventory manager, I get an alert when a shelf is empty beyond a configurable duration.
- **Business Value:** Faster restocking, more sales.
- **Acceptance Criteria:**
  - Alert is debounced to avoid noise.
  - Acknowledgement clears the alert.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-AI-INV-01`, `VM-NOTIF-01`

### `VM-AI-INV-03` — Restock workflow integration

- **Description:** As a stock clerk, I get a task list of shelves to restock, sorted by urgency.
- **Business Value:** Operational efficiency.
- **Acceptance Criteria:**
  - Tasks update in near real-time.
  - Completion is recorded with timestamp and user.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-AI-INV-02`

---

# Epic 15 — AI: Heatmap & Footfall (`AI-HEAT`)

### `VM-AI-HEAT-01` — Footfall counting at entrances

- **Description:** As an analyst, I see per-hour footfall for each branch entrance.
- **Business Value:** Marketing and staffing decisions.
- **Acceptance Criteria:**
  - Direction (in/out) is distinguished.
  - Accuracy benchmarked against manual count.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-AI-CORE-04`

### `VM-AI-HEAT-02` — Zone heatmap visualisation

- **Description:** As an analyst, I see a colour heatmap of foot traffic overlaid on a floor plan.
- **Business Value:** Reveals hot and dead zones.
- **Acceptance Criteria:**
  - Time-range filter (hour / day / week).
  - Aggregates only; no per-individual paths stored.
- **Priority:** P2 · **Complexity:** 13 · **Dependencies:** `VM-AI-HEAT-01`

### `VM-AI-HEAT-03` — Dwell time per zone

- **Description:** As an analyst, I see average dwell time per zone per time bucket.
- **Business Value:** Measures engagement.
- **Acceptance Criteria:**
  - Outliers (≥ 1 hour) are excluded.
  - Trends over weeks are charted.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-AI-HEAT-02`

---

# Epic 16 — AI: Queue Detection (`AI-QUEUE`)

### `VM-AI-QUEUE-01` — Queue length at checkout

- **Description:** As a duty manager, I see live queue length at each checkout.
- **Business Value:** Proactive staffing decisions.
- **Acceptance Criteria:**
  - Updates at least every 5 s.
  - Queue boundaries are configurable.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-AI-CORE-04`

### `VM-AI-QUEUE-02` — Wait-time estimate and SLA alert

- **Description:** As a duty manager, I get notified when estimated wait exceeds a threshold.
- **Business Value:** Reduces walk-aways.
- **Acceptance Criteria:**
  - Estimate based on rolling throughput.
  - Alert delivered via Notification Center.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-AI-QUEUE-01`, `VM-NOTIF-01`

---

# Epic 17 — AI: Loss Prevention / Theft Detection (`AI-LOSS`)

### `VM-AI-LOSS-01` — Suspicious-behaviour rules engine

- **Description:** As a loss-prevention officer, I can define rules (e.g. item taken without scan, restricted zone entry) that trigger alerts.
- **Business Value:** Reduces shrinkage.
- **Acceptance Criteria:**
  - Rules are versioned and previewable.
  - False-positive feedback retrains the score.
- **Priority:** P2 · **Complexity:** 21 · **Dependencies:** `VM-AI-PROD-02`, `VM-AI-CUST-01`

### `VM-AI-LOSS-02` — Incident workflow with evidence

- **Description:** As a loss-prevention officer, I review incidents with clip, snapshots, and tracked items, and mark each as confirmed, dismissed, or escalated.
- **Business Value:** Auditable LP process.
- **Acceptance Criteria:**
  - Each incident has a unique reference.
  - Disposition is mandatory before closure.
- **Priority:** P2 · **Complexity:** 13 · **Dependencies:** `VM-AI-LOSS-01`, `VM-STREAM-04`

---

# Epic 18 — Customer Analytics (`AN-CUST`)

### `VM-AN-CUST-01` — Daily / weekly footfall summary

- **Description:** As a manager, I see a chart of footfall by day and by hour.
- **Business Value:** Trend awareness.
- **Acceptance Criteria:**
  - Filter by branch and date range.
  - Export to CSV.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-AI-HEAT-01`

### `VM-AN-CUST-02` — Conversion rate (visitors → buyers)

- **Description:** As a manager, I see what percentage of visitors made a purchase.
- **Business Value:** Marketing effectiveness.
- **Acceptance Criteria:**
  - Per-branch and per-period.
  - Definition of "buyer" is documented.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-AN-CUST-01`, `VM-SALES-02`

### `VM-AN-CUST-03` — Customer frequency segments

- **Description:** As a marketer, I see distribution of customers by visit frequency (new, occasional, regular, VIP).
- **Business Value:** Targeted campaigns.
- **Acceptance Criteria:**
  - Segmentation thresholds configurable.
  - Drill-down to customer list.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-CUST-01`, `VM-AI-CUST-02`

---

# Epic 19 — Staff Analytics (`AN-STAFF`)

### `VM-AN-STAFF-01` — Camera-derived attendance

- **Description:** As a manager, I see when staff entered and left the staff zone.
- **Business Value:** Lightweight attendance signal.
- **Acceptance Criteria:**
  - Limited to designated staff cameras / zones.
  - Visible only to authorised roles.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-AI-CUST-01`, `VM-EMP-02`

### `VM-AN-STAFF-02` — Checkout productivity

- **Description:** As a manager, I see orders processed per cashier per hour.
- **Business Value:** Performance management.
- **Acceptance Criteria:**
  - Excludes refunds and voids.
  - Compared against branch average.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-SALES-02`, `VM-EMP-02`

### `VM-AN-STAFF-03` — Coverage vs footfall

- **Description:** As a manager, I see staff coverage overlaid with footfall to identify under-staffed periods.
- **Business Value:** Better scheduling.
- **Acceptance Criteria:**
  - Visualisation per branch per hour.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-AN-STAFF-01`, `VM-AI-HEAT-01`

---

# Epic 20 — Dashboard (`DASH`)

### `VM-DASH-01` — Manager landing dashboard

- **Description:** As a branch manager, I see today's revenue, orders, footfall, conversion, and active alerts on one page.
- **Business Value:** Single pane of glass.
- **Acceptance Criteria:**
  - Loads under 2 s on broadband.
  - Auto-refreshes every 30 s.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-SALES-02`, `VM-AI-HEAT-01`, `VM-NOTIF-01`

### `VM-DASH-02` — Live operations panel

- **Description:** As a duty manager, I see live camera tiles, current queues, and ongoing alerts.
- **Business Value:** Real-time response.
- **Acceptance Criteria:**
  - Updates via WebSocket.
  - Drill-down to camera or incident.
- **Priority:** P1 · **Complexity:** 13 · **Dependencies:** `VM-STREAM-01`, `VM-AI-QUEUE-01`, `VM-WS-01`

### `VM-DASH-03` — Customisable widget layout

- **Description:** As a user, I can rearrange dashboard widgets and save my layout.
- **Business Value:** Personalised workflow.
- **Acceptance Criteria:**
  - Layout persists per user.
  - Defaults restore via one click.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-DASH-01`

---

# Epic 21 — Reporting & Export (`RPT`)

### `VM-RPT-01` — Sales report (daily / weekly / monthly)

- **Description:** As a finance user, I can generate a sales report grouped by branch, category, and payment method.
- **Business Value:** Financial close.
- **Acceptance Criteria:**
  - Generated as PDF and XLSX.
  - Numbers reconcile with order data to the cent.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-SALES-02`

### `VM-RPT-02` — Inventory movement report

- **Description:** As an inventory manager, I can generate stock movement and variance reports.
- **Business Value:** Audit and reconciliation.
- **Acceptance Criteria:**
  - Filterable by branch, category, date.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-INV-02`

### `VM-RPT-03` — Scheduled report delivery

- **Description:** As a manager, I can schedule any report to be emailed daily / weekly / monthly.
- **Business Value:** Hands-off reporting.
- **Acceptance Criteria:**
  - Schedule is per user.
  - Failures notify the owner.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-RPT-01`, `VM-INFRA-07`, `VM-NOTIF-02`

### `VM-RPT-04` — Ad-hoc CSV export of any list view

- **Description:** As a user, I can export the current filtered list view to CSV.
- **Business Value:** Self-service data extraction.
- **Acceptance Criteria:**
  - Respects user's row-level permissions.
  - Large exports run as background jobs.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-INFRA-07`

---

# Epic 22 — Notification Center (`NOTIF`)

### `VM-NOTIF-01` — In-app notification inbox

- **Description:** As a user, I have an in-app inbox with unread counts and filters.
- **Business Value:** Central place for all alerts.
- **Acceptance Criteria:**
  - Mark-as-read syncs across devices.
  - Notifications older than retention TTL are archived.
- **Priority:** P0 · **Complexity:** 5 · **Dependencies:** `VM-AUTH-02`

### `VM-NOTIF-02` — Email channel

- **Description:** As a user, I can opt to receive selected notifications by email.
- **Business Value:** Reach users outside the app.
- **Acceptance Criteria:**
  - Templates per notification type.
  - SMTP credentials sourced from env.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-NOTIF-01`

### `VM-NOTIF-03` — Webhook channel for integrations

- **Description:** As an integrator, I can register a webhook URL to receive selected events.
- **Business Value:** Extensibility.
- **Acceptance Criteria:**
  - Signed payloads (HMAC).
  - Failed deliveries are retried with backoff.
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-NOTIF-01`

### `VM-NOTIF-04` — User preferences and quiet hours

- **Description:** As a user, I can choose which categories I receive on which channels and set quiet hours.
- **Business Value:** Reduces notification fatigue.
- **Acceptance Criteria:**
  - Quiet hours respect user timezone.
  - Critical-priority alerts ignore quiet hours.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-NOTIF-01`

---

# Epic 23 — Public REST API (`API`)

### `VM-API-01` — Versioned REST surface under `/api/v1`

- **Description:** As a client developer, every resource is reachable under a stable `/api/v1` prefix.
- **Business Value:** Backwards-compatible evolution.
- **Acceptance Criteria:**
  - Breaking changes require a new version.
  - Deprecations are announced via headers.
- **Priority:** P0 · **Complexity:** 3 · **Dependencies:** `VM-INFRA-01`

### `VM-API-02` — OpenAPI spec + Swagger UI

- **Description:** As a client developer, I have an interactive, always-up-to-date OpenAPI spec.
- **Business Value:** Reduces integration friction.
- **Acceptance Criteria:**
  - Spec is generated from the code.
  - Swagger UI is permission-gated in production.
- **Priority:** P0 · **Complexity:** 3 · **Dependencies:** `VM-API-01`

### `VM-API-03` — Consistent error model

- **Description:** As a client developer, every error response uses a documented schema with `code`, `message`, `details`.
- **Business Value:** Predictable error handling.
- **Acceptance Criteria:**
  - 100% of responses across the surface conform.
- **Priority:** P1 · **Complexity:** 3 · **Dependencies:** `VM-API-01`

### `VM-API-04` — Pagination, filtering, sorting standard

- **Description:** As a client developer, list endpoints follow a single convention for paging, filtering, and sorting.
- **Business Value:** Consistency.
- **Acceptance Criteria:**
  - Documented in the API guide.
  - All list endpoints comply.
- **Priority:** P1 · **Complexity:** 3 · **Dependencies:** `VM-API-01`

### `VM-API-05` — Rate limiting per token

- **Description:** As a platform operator, abusive clients are throttled by token or IP.
- **Business Value:** Protects availability.
- **Acceptance Criteria:**
  - Limits configurable per route.
  - Limit headers (`X-RateLimit-*`) are returned.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-INFRA-08`

### `VM-API-06` — Idempotency keys for mutating endpoints

- **Description:** As a client developer, I can safely retry POSTs using an `Idempotency-Key` header.
- **Business Value:** Prevents duplicate orders / payments on retry.
- **Acceptance Criteria:**
  - Keys are remembered for 24 h.
- **Priority:** P2 · **Complexity:** 5 · **Dependencies:** `VM-API-01`

---

# Epic 24 — Real-time WebSocket (`WS`)

### `VM-WS-01` — Authenticated WebSocket gateway

- **Description:** As a browser client, I can open an authenticated WebSocket and subscribe to topics.
- **Business Value:** Real-time UI without polling.
- **Acceptance Criteria:**
  - Auth handshake reuses access tokens.
  - Topic subscription is permission-checked.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-AUTH-03`

### `VM-WS-02` — Live detection / alert stream

- **Description:** As a dashboard user, I see new detections and alerts appear instantly.
- **Business Value:** Real-time situational awareness.
- **Acceptance Criteria:**
  - Push latency ≤ 500 ms inside the LAN.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-WS-01`, `VM-AI-CORE-05`

### `VM-WS-03` — Notification push channel

- **Description:** As a user, in-app notifications appear without reloading.
- **Business Value:** Modern UX.
- **Acceptance Criteria:**
  - Survives reconnects with backfill of missed messages.
- **Priority:** P1 · **Complexity:** 5 · **Dependencies:** `VM-WS-01`, `VM-NOTIF-01`

---

# Epic 25 — IoT MQTT Integration (`MQTT`)

### `VM-MQTT-01` — MQTT broker integration

- **Description:** As a platform engineer, the backend connects to an MQTT broker for edge devices.
- **Business Value:** Lightweight IoT transport.
- **Acceptance Criteria:**
  - TLS + per-device credentials.
  - Reconnects automatically.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-INFRA-01`

### `VM-MQTT-02` — Edge sensor ingestion (door, scale, weight)

- **Description:** As an operator, I can ingest events from edge sensors and correlate with vision events.
- **Business Value:** Enables hybrid AI + IoT scenarios.
- **Acceptance Criteria:**
  - Device registry with last-seen.
  - Schema validation per device type.
- **Priority:** P3 · **Complexity:** 8 · **Dependencies:** `VM-MQTT-01`, `VM-CAM-01`

---

# Epic 26 — Cloud Deployment & Scalability (`CLOUD`)

### `VM-CLOUD-01` — Stateless backend, externalised state

- **Description:** As a platform engineer, backend instances are stateless; sessions and queues live in Redis; binaries in MinIO/S3.
- **Business Value:** Horizontal scaling and rolling deploys.
- **Acceptance Criteria:**
  - Killing any backend pod does not lose user state.
- **Priority:** P0 · **Complexity:** 8 · **Dependencies:** `VM-INFRA-01`

### `VM-CLOUD-02` — Kubernetes / managed-cloud deployment manifests

- **Description:** As a platform engineer, I can deploy VisionMart to a Kubernetes cluster with documented manifests.
- **Business Value:** Production-grade orchestration.
- **Acceptance Criteria:**
  - Helm chart or Kustomize overlays exist.
  - Resource limits and requests defined.
- **Priority:** P1 · **Complexity:** 13 · **Dependencies:** `VM-CLOUD-01`

### `VM-CLOUD-03` — Auto-scaling backend and AI workers

- **Description:** As an SRE, the backend scales on CPU / RPS and AI workers scale on queue depth.
- **Business Value:** Cost-efficient performance.
- **Acceptance Criteria:**
  - HPA / KEDA configurations included.
  - Scale-up and scale-down events logged.
- **Priority:** P2 · **Complexity:** 8 · **Dependencies:** `VM-CLOUD-02`, `VM-INFRA-10`

### `VM-CLOUD-04` — Automated backup and restore

- **Description:** As an SRE, the Postgres database and MinIO buckets are backed up nightly with a documented restore procedure.
- **Business Value:** Disaster recovery.
- **Acceptance Criteria:**
  - Backup retention configurable.
  - Quarterly restore drill documented and passed.
- **Priority:** P1 · **Complexity:** 8 · **Dependencies:** `VM-INFRA-01`

### `VM-CLOUD-05` — Multi-region / edge deployment topology

- **Description:** As an architect, I can deploy AI processing close to cameras and the management plane in the cloud.
- **Business Value:** Latency and bandwidth efficiency.
- **Acceptance Criteria:**
  - Reference topology documented.
  - Data sovereignty constraints supported.
- **Priority:** P3 · **Complexity:** 21 · **Dependencies:** `VM-CLOUD-02`

---

# Epic 27 — Mobile App (Future) (`MOB`)

### `VM-MOB-01` — Manager mobile dashboard

- **Description:** As a manager away from the desk, I can see today's revenue, footfall, and active alerts on my phone.
- **Business Value:** Always-on visibility.
- **Acceptance Criteria:**
  - Reuses the same `/api/v1` surface.
  - Offline-tolerant for read-only views.
- **Priority:** P3 · **Complexity:** 21 · **Dependencies:** `VM-API-01`, `VM-AUTH-03`

### `VM-MOB-02` — Push notifications (APNs / FCM)

- **Description:** As a manager, critical alerts reach my phone as push notifications.
- **Business Value:** Faster incident response.
- **Acceptance Criteria:**
  - Per-device token registration.
  - User can mute non-critical pushes.
- **Priority:** P3 · **Complexity:** 13 · **Dependencies:** `VM-MOB-01`, `VM-NOTIF-01`

### `VM-MOB-03` — Mobile clerk app (scan, restock, stocktake)

- **Description:** As a store clerk, I can scan products and complete restock and stocktake tasks from my phone.
- **Business Value:** Replaces dedicated handheld terminals.
- **Acceptance Criteria:**
  - Works offline and syncs on reconnection.
- **Priority:** P3 · **Complexity:** 21 · **Dependencies:** `VM-MOB-01`, `VM-INV-05`

### `VM-MOB-04` — Customer companion app

- **Description:** As a shopper, I can view my purchase history, loyalty status, and current cart.
- **Business Value:** Loyalty engagement.
- **Acceptance Criteria:**
  - OAuth-style login.
  - Read-only access to own data.
- **Priority:** P4 · **Complexity:** 21 · **Dependencies:** `VM-MOB-01`, `VM-CUST-01`

---

## Suggested Release Plan (informational, not binding)

| Release | Theme | Epics |
|---------|-------|-------|
| **R1 — Foundation** | Stand up the platform, identity, and tenancy. | `INFRA`, `AUTH`, `ORG` |
| **R2 — Retail Core** | Sell things the traditional way. | `EMP`, `CUST` (basic), `CAT`, `INV`, `SALES` (cash + card), `DASH` (basic), `NOTIF`, `API` |
| **R3 — Vision Core** | Cameras + foundational AI online. | `CAM`, `STREAM`, `AI-CORE`, `WS` |
| **R4 — Smart Retail** | Differentiating AI features. | `AI-PROD`, `AI-CUST`, `SALES-08`, `AI-HEAT`, `AI-QUEUE` |
| **R5 — Operations & Analytics** | Loss prevention, deep analytics, scheduled reports. | `AI-INV`, `AI-LOSS`, `AN-CUST`, `AN-STAFF`, `RPT` |
| **R6 — Scale & Reach** | Cloud, IoT, and mobile. | `CLOUD`, `MQTT`, `MOB` |

---

*This backlog is a living document. Stories will be re-prioritised, split, and refined every sprint. Changes must preserve story IDs to keep history traceable.*
