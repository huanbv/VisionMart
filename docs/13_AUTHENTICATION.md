# VisionMart — Authentication & RBAC System Design

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/13_AUTHENTICATION.md`
> **Owner:** Lead Security Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** security and access-control system **design** only. No code,
> no implementation, no database DDL. Where this document conflicts with
> implementation, this document wins and the implementation **MUST** be
> refactored.
>
> **Companion documents:**
> [Architecture Contract §2.8](ARCHITECTURE_CONTRACT.md#28-security-rules) ·
> [Domain Model — Identity & Access](DOMAIN_MODEL.md#1-identity--access-context) ·
> [System Design — Security Design](SYSTEM_DESIGN.md#security-design) ·
> [Database Design — Identity tables](10_DATABASE_DESIGN.md)

---

# Authentication Overview

VisionMart authenticates **humans** (admins, branch managers, cashiers,
staff), **service accounts** (the AI Engine, integration partners), and
optionally **customers** (future mobile app). The authentication and
authorization layer must satisfy four hard requirements at the same
time:

1. **Multi-tenant isolation** — no principal **MAY** see data from
   another Organization. Ever.
2. **Multi-branch isolation** — a principal **MAY** see only the
   Branches they are explicitly assigned to.
3. **Real-time-friendly** — auth decisions are fast enough for live
   dashboards and WebSocket gateways under load.
4. **Stateless-by-design** — backend instances make auth decisions
   without per-request consultation of a central session store on the
   hot path.

### Design pillars

| # | Pillar | Translation |
|---|--------|-------------|
| 1 | **Stateless access tokens, stateful refresh** | Access decisions are made from a signed JWT; refresh tokens are tracked server-side and revocable. |
| 2 | **One layered policy enforcement point** | Auth checks happen in **one** middleware + decorator pipeline, not scattered across handlers. |
| 3 | **RBAC over ABAC for v1** | Roles + scopes (org/branch) are sufficient; pluggable ABAC is left as a future extension. |
| 4 | **Defence in depth** | API gateway, app middleware, repository scoping, and database constraints each independently enforce isolation. |
| 5 | **Audit everything that matters** | Auth events, permission denials, and consent changes are first-class audit records. |
| 6 | **Secrets never in source** | JWT signing keys, gateway secrets, and webhook HMAC secrets live in the secret manager. |
| 7 | **Rotation is normal** | Keys, refresh tokens, and API keys rotate without downtime. |

### What is in / out of scope

| In scope (v1) | Out of scope (future) |
|---------------|------------------------|
| Email + password login | Password-less login (magic link, WebAuthn) |
| JWT access + refresh tokens with rotation | Long-term issuer federation |
| RBAC with org-scoped and branch-scoped roles | Fine-grained ABAC rules engine |
| TOTP-based 2FA (planned for v1.2) | Hardware-key (WebAuthn) 2FA |
| API keys for service accounts | OAuth2 authorization-code grants for third parties |
| SSO via SAML / OIDC | First-party social login (Google, Apple) |

---

# User Model

> Conceptual identity model. See [Domain Model §1](DOMAIN_MODEL.md#1-identity--access-context)
> and [Database Design](10_DATABASE_DESIGN.md) for the canonical entity
> definitions.

### Principals

A **principal** is anyone or anything that can be authenticated. There
are three classes:

1. **User** — a human with credentials.
2. **Service account** — a non-human caller (AI Engine, integration
   partner) authenticated via an API key.
3. **System role** — an internal, principal-less identity used by
   background jobs running on behalf of a tenant.

### User entity (conceptual)

A `User` is described semantically by:

- A stable `user_id`.
- A binding to exactly **one** `organization_id`.
- A unique `email` (and `username`) per organization.
- A modern password hash (Argon2 / bcrypt-class), per-user salt — never
  plaintext.
- An `is_active` flag and an `is_superuser` flag (the latter is
  platform-wide).
- A `last_login_at` and login telemetry (failed attempts, lockout
  state).
- Optional `2FA configuration` (planned v1.2).
- Zero or more `Role` assignments (M:N).

### User types

| Type | Typical role | Org scope | Branch scope | Notes |
|------|--------------|-----------|--------------|-------|
| **Platform Super Admin** | `super_admin` | global | all | VisionMart staff only; not a customer role. |
| **Organization Admin** | `org_admin` | their org | all branches of their org | Full configuration rights inside the tenant. |
| **Branch Manager** | `branch_manager` | their org | their assigned branches | Day-to-day operations, hiring, scheduling. |
| **Cashier** | `cashier` | their org | one or more branches | POS + cart + payment. |
| **Floor Staff** | `staff` | their org | one or more branches | Inventory tasks, alerts, restock. |
| **Read-only / Viewer** | `viewer` | their org | configurable | Dashboard observers, finance reviewers. |
| **AI System Account** | `service:ai-engine` | per org | by camera assignment | Authenticates as a service account; calls a narrow surface. |
| **Integration Service Account** | custom | per org | as scoped by the API key | Webhook callers, ERP/POS adapters. |
| **Customer (future)** | `customer` | their org | n/a | Mobile / web companion app. |

### How users link to Organization, Branch, and Role

- **User ↔ Organization:** strict **N:1**. Every user belongs to
  exactly one organization. A user **cannot** be moved between
  organizations; identity is a new account.
- **User ↔ Role:** **M:N** via a `UserRole` link. A role itself is
  organization-scoped (except platform-level roles like
  `super_admin`).
- **User ↔ Branch:** **M:N** via an explicit assignment. Org-wide
  roles imply all branches; branch-scoped roles require explicit
  assignment.
- **Role ↔ Permission:** **M:N**; permissions are a global catalogue;
  roles select from it.

> Two cardinality rules are non-negotiable: *one user, one
> organization* and *a service-account principal is always tenant-
> scoped*.

---

# RBAC Design

### Vocabulary

| Term | Meaning |
|------|---------|
| **Permission** | An atomic capability, in `resource.action` form. Always a single English noun + verb. |
| **Role** | A named bundle of permissions. Carries `org-scope` and `branch-scope` flags. |
| **Assignment** | A `(user, role, branch?)` triple that grants a role to a user, optionally narrowed to one or more branches. |
| **Effective permissions** | The set of `(permission, scope)` pairs produced by union-ing all of a principal's assignments. |

### Permission naming convention (canonical)

Permissions are written `<resource>.<action>` in lowercase, dot-
separated. The resource is **singular**; the action is a verb in the
present tense.

| Resource | Common actions |
|----------|----------------|
| `org`, `branch` | `read`, `update`, `admin` |
| `user`, `role`, `permission`, `apikey` | `read`, `create`, `update`, `delete`, `assign` |
| `product`, `category` | `create`, `update`, `delete`, `read` |
| `inventory` | `view`, `adjust`, `transfer`, `stocktake` |
| `cart`, `order`, `payment`, `refund` | `view`, `create`, `manage`, `cancel`, `issue` |
| `customer`, `customer.face` | `read`, `update`, `merge`, `link`, `recognise` |
| `camera`, `stream`, `snapshot` | `view`, `register`, `configure`, `delete` |
| `ai`, `ai.model` | `read`, `configure`, `deploy` |
| `notification`, `webhook` | `read`, `send`, `subscribe`, `manage` |
| `report`, `analytics` | `view`, `export`, `schedule` |
| `audit` | `view`, `export` |

### Example permissions (illustrative subset)

- `product.create`, `product.update`, `product.delete`
- `inventory.view`, `inventory.adjust`, `inventory.transfer`
- `cart.create`, `cart.manage`, `order.manage`, `payment.issue`,
  `refund.issue`
- `camera.view`, `camera.register`, `camera.configure`
- `ai.read`, `ai.configure`, `ai.model.deploy`
- `customer.read`, `customer.face.link`, `customer.face.recognise`
- `branch.admin`, `branch.read`
- `audit.view`

### Seed roles (shipped with the platform)

| Role code | Scope | Sample permissions |
|-----------|-------|--------------------|
| `super_admin` | platform | All. |
| `org_admin` | org | All `org.*`, `user.*`, `role.*`, `branch.admin`, `audit.view`, all module admin permissions. |
| `branch_manager` | branch | `branch.read`, `inventory.*`, `order.manage`, `refund.issue`, `camera.view`, `report.view`, `notification.read`. |
| `cashier` | branch | `cart.*`, `order.manage` (limited), `payment.issue`, `customer.read`, `inventory.view`. |
| `staff` | branch | `inventory.view`, `inventory.adjust` (limited reasons), `notification.read`, `camera.view`. |
| `viewer` | configurable | `*.view`, `report.view`, `analytics.view` only. |
| `service:ai-engine` | branch (by camera assignment) | `ai.read`, `ai.event.publish`, `snapshot.create`, narrow `cart.suggest` capability. |

### Role hierarchy

- VisionMart uses a **flat** RBAC model: a role's permissions are the
  exact list assigned to it. There is **no implicit inheritance** (a
  `branch_manager` does **not** automatically inherit `org_admin`).
- The illusion of hierarchy is achieved at seed time by assigning the
  same permission to multiple roles. This avoids the surprises common
  to inheritance-based RBAC.

### How permissions are assigned

1. The platform ships with **immutable seed permissions** and
   **mutable role definitions**.
2. An `org_admin` can:
   - Create custom roles.
   - Edit a role's permission set (within the platform's allowed
     surface).
   - Assign a role to a user — globally (org-wide role) or scoped to
     one or more branches (branch-scoped role).
3. Assignments are audited (`role.assigned`, `role.revoked`).

### How role checks are enforced

- Every protected endpoint **MUST** declare its required permission(s)
  in a single declarative form (a decorator-style annotation in the
  presentation layer; conceptually `@requires("inventory.adjust")`).
- A request that reaches the application layer **without** having
  passed the permission check is a CI failure: the policy enforcement
  point rejects any path that did not register a required permission.
- Permission checks **never** live inside the domain layer (the domain
  remains framework-free).

### Middleware role validation flow

```
request → auth middleware → permission middleware → branch-scope middleware → handler
                  │                  │                       │
                  │                  │                       └─ enforces allowed_branch_ids
                  │                  └─ verifies the declared permission is in effective set
                  └─ verifies the JWT, loads principal
```

- All three middlewares share an immutable **`Principal`** object
  attached to the request context.
- A failure at any stage short-circuits with a structured error
  envelope and emits an audit event.

---

# Multi-Branch Security

### Hard rules

- **R-1.** Every business row that pertains to operations carries
  `organization_id` and, where applicable, `branch_id`.
- **R-2.** A principal **MUST NEVER** read or modify rows from another
  `organization_id`. This is enforced at four layers (see *Defence in
  depth* below).
- **R-3.** A principal **MUST** be limited to the set of `branch_id`s
  derived from their effective assignments. Branch-narrowing is
  authoritative on the backend; UI filters are advisory.
- **R-4.** Org-wide roles (`org_admin`, `super_admin`) implicitly
  match all branches of their organization.
- **R-5.** Cross-tenant access is **only** possible for
  `super_admin`, and that access is audited per request.

### Defence in depth

| Layer | What it enforces |
|-------|------------------|
| **API gateway (Nginx)** | TLS, rate limits, basic header sanity. Not auth-aware. |
| **Auth middleware (backend)** | JWT signature/expiry, principal hydration. |
| **Permission middleware** | The required permission is in the principal's effective set. |
| **Scope middleware** | The request targets the principal's organization, and any branch in the request is in `allowed_branch_ids`. |
| **Repository layer** | Every tenant-scoped query injects `organization_id = :org` and `branch_id IN :branches` predicates. Raw SQL is reviewed. |
| **Database constraints** | FK + tenant columns prevent some classes of cross-tenant insert; indexes on tenant columns make missing predicates a performance cliff (encouraging the right pattern). |
| **(Future)** Row-Level Security (RLS) | Belt-and-braces below the repository. |

### Cross-branch access rules

- **Read across branches** is permitted only when the role grants an
  org-wide `read` permission (e.g. `report.view.all` — to be defined
  per resource).
- **Write across branches** is permitted only with explicit
  `branch.admin` and is always audited.
- **AI Engine / service accounts** never access across-branch; they
  access only the branches whose cameras they are assigned to.

### Admin override rules

- An `org_admin` may operate on any branch in their organization but
  **MUST** still respect the data isolation predicates. There is no
  "ignore branch filter" feature; the effect of `org_admin` is that
  their `allowed_branch_ids` is **the full set** for their
  organization.
- A `super_admin` can act across organizations but **MUST** assume an
  explicit *operating organization* for any data-touching action.
  Implicit cross-org reads are forbidden.

### Preventing data leakage between branches

1. **Compile-time check:** code review and lint rules forbid hand-
   written SQL outside the repository layer.
2. **Run-time check:** repository base methods refuse to execute
   without a scope predicate when called on a scoped table.
3. **Test gate:** the test suite includes deliberate cross-branch and
   cross-tenant access attempts; they **MUST** fail.
4. **Telemetry:** every `PermissionDenied` event is audited; spikes
   alert security.

### Query-level enforcement strategy

- The request principal is the **only** legitimate source of
  `organization_id` and `allowed_branch_ids`. Clients **MUST NOT** be
  able to pass these as overriding parameters.
- For list endpoints, the principal's branch scope **intersects** the
  user-supplied branch filter, never overrides it.
- For single-item endpoints, the loaded row's `organization_id` and
  `branch_id` are re-checked against the principal **after** the
  query returns — a defence against query-shape mistakes.

---

# Authorization Flow

### Full request lifecycle (REST)

```
[Client]
   │  HTTPS request, Authorization: Bearer <access JWT>
   ▼
[Nginx]
   │  TLS terminate · rate limit · security headers
   ▼
[Backend — Auth Middleware]
   │  verify JWT signature + expiry, hydrate Principal (user_id,
   │  org_id, roles, allowed_branch_ids, scope claims, jti)
   ▼
[Backend — Permission Middleware]
   │  read the endpoint's required permission(s); confirm Principal
   │  has each in their effective set (or 403)
   ▼
[Backend — Scope Middleware]
   │  ensure org_id matches; ensure branch_id (if in request) is in
   │  allowed_branch_ids; inject scope into the application call
   ▼
[Application Service]
   │  orchestrates domain + repositories; runs in one transaction
   ▼
[Repositories]
   │  inject tenant + branch predicates automatically
   ▼
[Postgres]   [Redis]   [MinIO]
   │
   ▼
[Response] — standard envelope:
   { "success": true, "data": ..., "message": "", "error": null }

[Audit] — every privileged action records who, what, where, when, why
```

### WebSocket lifecycle

- The handshake carries the same access JWT (as a query parameter at
  open time, or via the `Sec-WebSocket-Protocol` header — chosen to
  remain compatible with browser APIs).
- The Principal is hydrated **once** at handshake; the connection's
  permitted topics are derived from it.
- **Every `subscribe` message** is permission-checked. There is no
  blanket "subscribe to everything" capability.
- A revoked refresh-token *lineage* causes the gateway to close
  affected connections within the revocation propagation window.

### Failure responses

- 401 — token missing / invalid / expired.
- 403 — token valid but the principal lacks the required permission or
  scope.
- 423 — account locked (lockout / disabled / consent revoked
  upstream).
- 429 — rate-limit exceeded.

All 4xx auth-related responses use the standard envelope and a stable
error code (e.g. `AUTH_TOKEN_EXPIRED`, `AUTHZ_PERMISSION_DENIED`,
`AUTHZ_BRANCH_DENIED`).

---

# Security Layers

### Edge (Nginx) — perimeter security

- TLS 1.2+ termination (TLS 1.3 preferred); HSTS preload-eligible.
- Security headers: HSTS, CSP, X-Content-Type-Options,
  Referrer-Policy, X-Frame-Options.
- Per-route rate limits; stricter on `/auth/*`.
- Request size limits to defeat bulk-upload abuse.
- IP-based blocklist (operator-managed) for known abusers.
- **Not auth-aware** by design — the gateway is dumb so the policy
  surface stays unified in the backend.

### API middleware (backend) — application security

- **Auth middleware:** JWT verification, principal hydration, request
  context construction, `X-Request-ID` propagation.
- **Permission middleware:** declarative permission enforcement.
- **Scope middleware:** tenant + branch scope enforcement.
- **CSRF protection** for any same-origin cookie-based path (the SPA
  uses bearer tokens; the cookie path is reserved for future
  enhancements).
- **Idempotency middleware** for mutating endpoints.
- **Output sanitisation** — error responses never leak stack traces;
  exceptions are mapped to stable codes.

### Service-level validation — domain and application security

- **Application services** re-validate inputs at the use-case
  boundary, even when the API has validated them — defence in depth.
- **Aggregates** protect invariants (e.g. an `Order` will refuse to
  transition out of `PAID`).
- **Repositories** apply tenant/branch scoping; queries that bypass
  the base methods are forbidden by code review and lint.
- **Background jobs** carry an explicit principal context derived from
  the job's payload (audited at enqueue and at execute time).

---

# Token Strategy

### Token types

| Type | Form | TTL (typical) | Where stored on client | Server state |
|------|------|---------------|------------------------|--------------|
| **Access token** | Signed JWT | ≤ 15 min | In-memory (or HttpOnly cookie) | None (stateless) |
| **Refresh token** | Opaque random string | ≤ 14 days | Most restrictive client storage available | Hashed server-side, revocable |
| **API key (service account)** | Opaque random string | rotating | Stored by the integrator; never in source | Hashed server-side, scoped |
| **One-time tokens** (password reset, email verify, invite) | Signed, single-use | 30–72 h | URL | Marked used at first use |
| **2FA TOTP secret** (planned) | per-user secret | n/a (rotation possible) | On the user's device (RFC 6238) | Stored encrypted on server |

### JWT payload (conceptual claims — never put PII in the token)

| Claim | Meaning |
|-------|---------|
| `iss` | The VisionMart issuer URL. |
| `aud` | The VisionMart audience (e.g. `visionmart-backend`). |
| `sub` | The `user_id`. |
| `org` | The `organization_id`. |
| `branches` | Compact list of `allowed_branch_ids` (or `*` for org-wide). |
| `roles` | Compact list of role codes. |
| `scope` | Compact list of permission codes effective for this token. |
| `iat`, `nbf`, `exp` | Standard time claims. |
| `jti` | Unique token id (used for revocation correlation). |
| `kid` | Key id, in the JWT header, for rotation. |
| `mfa` | Boolean — was MFA satisfied this session. |
| `act` | Optional — for "act-as" impersonation by super_admin; audited. |

The token **does not** contain emails, names, phone numbers,
attributes, or any PII beyond identifiers.

### Signing key strategy

- **Asymmetric (RS256 / EdDSA)** preferred so resource servers
  (potentially separate services later) verify with a public key
  without holding the private key.
- Private signing key sourced from the **secret manager**; never
  committed.
- **Key rotation**:
  - JWKS endpoint publishes the current set of public keys.
  - Tokens carry `kid` so verifiers select the correct key.
  - Rotation overlaps — both old and new keys are valid until the old
    one expires, after which it is removed.
- Symmetric (HS256) is allowed for single-process dev only and is
  refused in production via configuration validation.

### Refresh token strategy

- Refresh tokens are **opaque random strings** of high entropy.
- Stored **hashed** server-side, indexed by user, with `issued_at`,
  `expires_at`, `device_label`, `last_used_at`, and a lineage
  identifier.
- **Rotated on every use** — a successful refresh issues a new
  refresh token and invalidates the previous one.
- **Reuse detection** — presenting an already-rotated refresh token
  invalidates the whole lineage and forces re-login. This catches
  refresh-token theft.
- **Revocation** — explicit logout (single-device or global) marks
  the lineage revoked.

### Token revocation strategy

- **Access tokens** are short-lived; immediate revocation is not
  required.
- For high-sensitivity scenarios (admin lockout, theft response) a
  **server-side revocation list** in Redis holds `jti`s of access
  tokens to deny **until their natural expiry**. Auth middleware
  checks this list as a fast Redis lookup.
- **Refresh-token revocation** is authoritative server-side.
- **WebSocket gateways** subscribe to revocation events and close
  affected connections within the propagation SLO.

### Token transport rules

- **HTTPS only.** Tokens **MUST NOT** transit over plaintext HTTP.
- **Never** in URL paths or query strings outside narrowly-scoped
  one-time tokens.
- **Never** logged. Token values are scrubbed from logs and error
  reports.

---

# Audit System

### Audit events (security-relevant subset)

| Event | When emitted |
|-------|--------------|
| `auth.login.succeeded` | Successful credential check. |
| `auth.login.failed` | Failed credential check (with reason). |
| `auth.locked` | Account locked after N consecutive failures. |
| `auth.unlocked` | Admin or self-service unlock. |
| `auth.password_reset_requested` | Reset email requested. |
| `auth.password_changed` | Password successfully changed. |
| `auth.logout` | Single-device logout. |
| `auth.session_revoked` | Single or all sessions revoked. |
| `auth.mfa_enrolled` / `auth.mfa_removed` | 2FA configuration changes. |
| `auth.refresh.rotated` | Normal refresh. |
| `auth.refresh.reuse_detected` | Suspected theft; lineage revoked. |
| `authz.permission_denied` | A request was refused by RBAC. |
| `authz.branch_denied` | A request targeted a forbidden branch. |
| `authz.cross_tenant_attempt` | Any non-`super_admin` cross-tenant attempt. |
| `apikey.created` / `apikey.revoked` | Service-account credential lifecycle. |
| `role.assigned` / `role.revoked` | RBAC membership changes. |
| `consent.granted` / `consent.withdrawn` | Customer consent state changes (privacy). |
| `order.refunded` | Sensitive financial action. |
| `model.deployed` | AI model active version changed. |

### Audit record structure (conceptual)

Each record carries:

- `correlation_id` (the originating request's `X-Request-ID`),
- `actor_type` (`user`, `service_account`, `system`, `ai_engine`),
- `actor_id`, `organization_id`, `branch_id` (when applicable),
- `action`, `resource_type`, `resource_id`,
- `ip_address`, `user_agent`, `outcome` (`succeeded`/`denied`/`failed`),
- a structured `metadata` payload (no secrets, no full tokens, no
  unsanitised PII).

Audit records are **append-only**, partitioned by month, and retained
per regulatory floor (typically ≥ 1 year hot, then cold archive with
object lock).

### Sensitive-action tracking

Sensitive actions get **synchronous** audit writes in the same
transaction as the business mutation:

- Refunds, order cancellations after payment.
- Role and permission changes.
- API key creation / rotation / revocation.
- Consent grants and withdrawals.
- Cross-tenant `super_admin` operations.
- Model deployments.

Failure to write the audit row **MUST** abort the business mutation.

### Failed-login / abuse handling

- Per-IP and per-account counters in Redis with sliding windows.
- After N consecutive failures: progressive backoff → temporary
  lockout → permanent lockout requiring admin unlock.
- Burst protections at the edge (Nginx rate limits) catch broad
  scans before they hit the backend.
- Audit + alerting trigger when the per-tenant denial rate exceeds a
  configured baseline.

---

# AI Security Model

### AI Engine as a service account

- The AI Engine authenticates to the backend as a **service account**
  (`service:ai-engine`) using an API key issued per organization (and
  optionally per node).
- The API key is scoped to:
  - Reading the cameras assigned to the engine (`camera.view`,
    `ai.read`).
  - Publishing AI events for those cameras (`ai.event.publish`).
  - Uploading snapshots to the AI evidence bucket via backend-issued
    signed URLs.
  - **Nothing else.** No direct DB, no broad reads, no writes to
    business tables.
- Keys are rotatable; rotation is staged (overlap window).

### Camera access control

- Cameras are tenant-scoped resources. A user with `camera.view`
  scoped to a branch can see only that branch's cameras.
- Live stream subscriptions over WebSocket are subscribed by topic
  (`org.{id}.camera.{cameraId}.stream`) and are permission-checked at
  subscribe time.
- The AI Engine receives camera-attach assignments from the backend;
  it cannot enumerate cameras it is not assigned to.

### AI event authorization rules

- AI events arriving from the AI Engine are accepted only when the
  presenting API key is scoped to the originating camera's
  organization (and branch).
- Each AI event is **validated** at the boundary:
  - `camera_id` must be one the service is assigned to.
  - `event_type` must be in the published AI event catalogue.
  - `confidence` must be present and within `[0, 1]`.
  - `occurred_at` must be within a small skew window of server time.
- Events that fail validation are rejected and audited as
  `ai.event.rejected`.
- AI is **never** allowed to bypass the application layer — it
  emits events; the backend decides whether business state changes
  (Architecture Contract §2.2; Business Rule BR-28).

### Privacy for face recognition

- Face recognition operates **only** on customers with active
  `CustomerConsent` for `FACE_RECOGNITION`.
- Withdrawal of consent triggers a backend-led purge of embeddings
  within the documented privacy SLA; the AI Engine receives an
  invalidation signal.
- Embeddings are stored in MinIO under bucket policies that the AI
  Engine cannot list — it accesses individual embeddings only via
  backend-issued signed URLs scoped to a single customer at a time.

### Customer mobile app (future)

- Authenticated via the same JWT scheme with a `customer` audience
  and a narrow permission set (`order.self.read`, etc.).
- A customer principal **MUST NEVER** be confused with a `User`
  principal — they live on a separate audience and cannot be issued
  staff tokens.

---

# Threat Model

| Threat | Description | Mitigations |
|--------|-------------|-------------|
| **Unauthorized branch access** | A branch-scoped user attempts to reach data of an unassigned branch. | Branch-scope middleware + repository predicates + post-load re-check + audit (`authz.branch_denied`) + negative regression tests. |
| **Cross-tenant data leak** | A user or query returns rows from another organization. | `organization_id` predicate at repository layer; lint forbidding raw SQL; post-load re-check; negative tests; optional RLS as defence-in-depth. |
| **Stolen access token (XSS, log leak, MITM)** | Attacker reuses a captured JWT. | Short TTL; HTTPS only; in-memory / HttpOnly storage; access-token revocation list in Redis for high-sensitivity cases; CSP + strict React encoding; logs scrubbed. |
| **Stolen refresh token** | Attacker uses a captured refresh token. | Hashed server-side; **single-use rotation**; **reuse detection** invalidates the lineage and forces re-login; lineage audit. |
| **Credential stuffing / brute force** | Attacker tries known username + password lists. | Per-account and per-IP rate limit; progressive backoff; lockout; CAPTCHA on suspected abuse (future); 2FA option. |
| **Password reset abuse** | Attacker triggers resets to enumerate accounts. | Reset endpoint never reveals whether an email exists; reset tokens single-use and short-lived; rate-limited. |
| **Token forgery / weak crypto** | Attacker forges a token. | Asymmetric signing (RS256 / EdDSA); private key in secret manager; key rotation; JWKS with `kid`; algorithm pinning in verifier (no `alg=none`, no algorithm confusion). |
| **API abuse / DoS** | Attacker floods endpoints. | Edge rate limits; per-token rate limits; expensive endpoints behind stricter limits; backpressure on background queues. |
| **Privilege escalation via role edit** | A non-admin gains higher permissions. | Role edits require `role.assign` permission; permission set is bounded by tenant-allowed surface; audited. |
| **API-key leakage** | Service-account key checked into a repo. | Keys are hashed server-side (raw shown once at creation); rotation supported; scoped narrowly; usage logged and rate-limited. |
| **Insider abuse** | Authorized user misuses access. | Comprehensive audit log; access reviews; just-in-time elevation for sensitive ops; alerting on anomalous patterns. |
| **Replay of mutating requests** | A captured POST is retried by an attacker. | Idempotency keys on mutating endpoints; short TTLs on bearer tokens. |
| **Session fixation / improper logout** | Token stays valid after logout. | Logout revokes refresh lineage; high-sensitivity sessions also place access JTI on the revocation list. |
| **Frontend secret exposure** | UI accidentally leaks data via dev tools / source maps. | No secrets in the SPA; source maps stripped or restricted; only the current view's data is loaded. |
| **AI event spoofing** | An attacker emits fake events as if from the AI Engine. | API-key authentication; per-event boundary validation; tight schemas; events do not change state directly — backend application services arbitrate. |
| **Snapshot exfiltration** | An attacker downloads camera snapshots from MinIO. | Buckets are private; access only via short-lived backend-issued signed URLs; bucket policies least-privilege; audit on snapshot read. |

---

# Scalability Plan

### Multiple branches per organization

- Branch scoping is a **predicate** on rows, not a separate
  schema/database. Adding branches is O(1) operationally and scales
  linearly with index usage.
- Auth decisions are constant-time on the size of the principal's
  `allowed_branch_ids` (typically very small).

### Future mobile app (manager / clerk / customer)

- The mobile app authenticates with the same JWT scheme; mobile-
  specific concerns (longer refresh windows, device binding, push
  registration) are handled per-audience.
- Per-device refresh tokens permit per-device revocation ("sign out
  this iPhone") without affecting other devices.

### Future SaaS customers (multi-organization)

- Multi-tenant by row is the default; **schema-per-tenant** or
  **DB-per-tenant** is available for premium customers — the auth
  model already separates tenant context from the user identity, so
  promotion is a deployment choice, not a code change.
- Per-tenant SSO (SAML / OIDC) is a future enhancement; the user
  model already supports external identity providers because the
  user record is decoupled from the password (password becomes
  optional when SSO is enabled).

### High concurrent users

- Access decisions are **stateless** — adding API instances scales
  auth throughput linearly.
- Refresh token validation and revocation lookups go to Redis with
  sub-millisecond latency.
- WebSocket auth happens once per connection (at handshake); only
  topic subscribes cost more.
- JWKS keys are cached at every verifier with rotation-aware
  invalidation.

### Operational scalability

- Per-tenant rate limits prevent one noisy tenant from impacting
  another.
- Per-route rate limits prevent expensive endpoints from saturating
  the database.
- Background workloads run on dedicated Celery queues so foreground
  auth latency is not affected by report jobs.

---

# Future Improvements

> Tracked for visibility; promoted into the roadmap or a new ADR when a
> real trigger appears.

### Identity

- **SSO** via SAML 2.0 and OpenID Connect for enterprise tenants.
- **WebAuthn / passkeys** as a passwordless / phishing-resistant
  factor.
- **SCIM** provisioning for enterprise customers.
- **Customer login** via OAuth-style flows in the mobile companion
  app.

### Authorization

- **Attribute-Based Access Control (ABAC)** layered on top of RBAC
  for cases like "this report only for cashiers in branches X, Y
  during business hours."
- **Policy-as-code** (OPA / Cedar) for centralised, auditable
  authorization decisions.
- **Just-in-time elevation** ("break-glass") for sensitive admin
  operations, with mandatory justification and tight TTL.

### Crypto

- **Hardware-backed signing keys** (HSM / KMS-managed) for JWT
  signing.
- **Per-tenant signing keys** so a compromise can be contained to one
  tenant.
- **Post-quantum-ready** algorithm choices where libraries mature.

### Anti-abuse

- Adaptive rate limiting and bot detection at the edge.
- Risk-based authentication (impossible-travel, device anomalies).
- Honeytoken accounts to detect credential-database leaks.

### Operations

- Tenant-level **audit export** in a tamper-evident format (e.g.
  signed logs).
- Automated **access reviews** — managers re-attest their team's
  permissions on a schedule.
- A self-service **security console** for tenant admins (sessions,
  API keys, audit, anomalies).

### Anti-goals (deliberately not on the plan)

- Custom-built password hashing or token signing — we use battle-
  tested libraries.
- "Permission inheritance" hierarchies — they cause more security
  bugs than they solve.
- Storing biometric or PII data in the JWT.
- Long-lived (> weeks) access tokens.
- Single super-key shared between services.

---

*This document is the canonical authentication and RBAC design. Any
change to the auth flow, token strategy, RBAC model, or threat model
requires a PR that updates **only this file** (and, when needed, an ADR
explaining the rationale).*
