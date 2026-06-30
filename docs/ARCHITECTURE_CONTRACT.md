# VisionMart — Architecture Contract

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/ARCHITECTURE_CONTRACT.md`
> **Owner:** Chief System Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30

> ## This Document is the SINGLE SOURCE OF TRUTH
>
> Every line of code merged into VisionMart — written by humans or AI — **must
> comply** with this contract. When this contract conflicts with any other
> document, **this contract wins**. The only legal way to change a rule here is
> a pull request that touches *only this file* and is approved by the Chief
> System Architect.
>
> Normative keywords (**MUST**, **MUST NOT**, **SHALL**, **SHALL NOT**,
> **SHOULD**, **MAY**) follow [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

---

## Table of Contents

1. [System Principles](#1-system-principles)
2. [Core Architecture Rules](#2-core-architecture-rules)
   - 2.1 [Layer Structure (Mandatory)](#21-layer-structure-mandatory)
   - 2.2 [AI Engine Rules](#22-ai-engine-rules)
   - 2.3 [Event-Driven Design](#23-event-driven-design)
   - 2.4 [Data Flow Rules](#24-data-flow-rules)
   - 2.5 [Module Isolation Rules](#25-module-isolation-rules)
   - 2.6 [Database Rules](#26-database-rules)
   - 2.7 [API Rules](#27-api-rules)
   - 2.8 [Security Rules](#28-security-rules)
   - 2.9 [Scalability Rules](#29-scalability-rules)
3. [Non-Functional Requirements](#3-non-functional-requirements)
4. [Technology Boundaries](#4-technology-boundaries)
5. [Enforcement and Exceptions](#5-enforcement-and-exceptions)
6. [Strict Rule](#6-strict-rule)
7. [Glossary](#7-glossary)

---

## 1. System Principles

VisionMart **MUST** be built on the following principles. They are
non-negotiable and apply to every service, every module, every commit.

| # | Principle | What it means here |
|---|-----------|--------------------|
| 1 | **Clean Architecture** | Dependencies point inward. The domain layer depends on nothing; the API depends on application; application depends on domain. |
| 2 | **Domain Driven Design (DDD)** | The codebase is organised by **bounded contexts**. Each context owns its aggregates and its ubiquitous language. |
| 3 | **Modular Monolith (MVP stage)** | One deployable backend process containing many independent modules. Extraction into separate services is allowed *later*, never required *now*. |
| 4 | **Event-Driven Ready** | Cross-context communication is expressed as **domain events**. The transport (in-memory bus, Redis Streams, NATS, RabbitMQ, Kafka) is pluggable. |
| 5 | **API First Design** | Every feature begins with a versioned REST contract under `/api/v1/...`. OpenAPI is the source of truth for clients. |
| 6 | **Separation of Concerns** | Presentation, application, domain, and infrastructure code live in different files and different layers. No file mixes them. |
| 7 | **Dependency Inversion** | High-level modules depend on **abstractions** (interfaces, protocols), never on concrete infrastructure. |
| 8 | **Stateless Backend Services** | Backend instances **MUST NOT** keep per-request state in memory. All session, cache, queue, and binary state lives in Redis, Postgres, or MinIO. |

---

## 2. Core Architecture Rules

### 2.1 Layer Structure (MANDATORY)

The backend **MUST** be organised into exactly four layers. Inside any
bounded context (`backend/app/modules/<context>/`), the structure is:

```
Presentation Layer (API)        backend/app/modules/<ctx>/api/
        │
        ▼
Application Layer (Use Cases)   backend/app/modules/<ctx>/application/
        │
        ▼
Domain Layer (Business Logic)   backend/app/modules/<ctx>/domain/
        │
        ▼
Infrastructure Layer            backend/app/modules/<ctx>/infrastructure/
(Database, External Services)
```

#### Layer responsibilities

| Layer | Allowed to contain | **MUST NOT** contain |
|-------|--------------------|----------------------|
| **Presentation (API)** | FastAPI routers, request/response DTOs (Pydantic), HTTP error mapping. | Business rules, SQL, direct DB access. |
| **Application** | Use cases / services, commands, queries, orchestration of repositories and domain objects, transaction boundaries. | HTTP details, ORM models, framework imports. |
| **Domain** | Entities, value objects, domain events, domain services, invariants. | Imports from `infrastructure`, `application`, `api`, FastAPI, SQLAlchemy, Pydantic, Redis, MinIO, Celery, anything outside `app.domain.*` and Python stdlib. |
| **Infrastructure** | ORM models, repository implementations, external API clients, cache adapters, file storage adapters, message-broker adapters. | Business rules. |

#### Hard rules

- A layer **MUST NOT** bypass the layer directly above it.
  - The API layer **MUST NOT** call the infrastructure layer directly.
  - The application layer **MUST NOT** instantiate ORM models — it talks to
    repository interfaces.
- The **domain layer imports nothing from the other layers**. This is
  enforced by import-linting in CI.
- Transaction boundaries are owned by the **application layer**, never by
  repositories and never by the API layer.

### 2.2 AI Engine Rules

The AI Engine **MUST** be an isolated module deployable as its own process.

- The AI Engine **MUST NOT** access the frontend directly.
- The AI Engine **MUST NOT** access the database directly. Not Postgres, not
  Redis, not MinIO buckets that belong to backend ownership.
- The AI Engine **MUST** communicate only through:
  1. The backend's published HTTP / gRPC interface, or
  2. The shared event interface (`EventBus`).
- The AI Engine **MAY** read frames from RTSP / RTMP / HTTP camera sources
  and **MAY** write AI artefacts (e.g. embeddings, snapshots) to MinIO
  *only* through a backend-issued signed URL or a backend-mediated service.

#### Mandatory pipeline shape

```
Camera ─► Frame Capture ─► AI Processing ─► Event Generation ─► Backend
```

Each arrow is a hard boundary. Frame capture, processing, and event
generation **MUST** be independently testable. Each stage **MUST** publish
metrics for latency and error rate.

### 2.3 Event-Driven Design

VisionMart **MUST** be designed to support event-driven architecture from
day one, even while a single in-process bus is sufficient.

#### Canonical domain events

The following events form the **initial public catalogue**. New events
require a pull request that updates this list.

| Event | Producer (context) | Typical consumers |
|-------|--------------------|-------------------|
| `CustomerDetected` | `ai-core` / `customer` | `analytics`, `notification` |
| `ProductDetected` | `ai-core` | `sales`, `inventory`, `analytics` |
| `ProductAddedToCart` | `sales` | `inventory`, `notification` |
| `ProductRemovedFromCart` | `sales` | `inventory` |
| `InventoryUpdated` | `inventory` | `notification`, `analytics` |
| `TheftDetected` | `ai-loss` | `notification`, `audit` |
| `QueueDetected` | `ai-queue` | `dashboard`, `notification` |
| `HeatmapUpdated` | `ai-heat` | `analytics`, `dashboard` |
| `PaymentCompleted` | `sales` | `inventory`, `notification`, `analytics`, `audit` |

#### Event rules

- Events **MUST** be **decoupled from business logic**: business decisions
  are taken by application services; events merely *announce* what happened.
- Every event **MUST** carry `event_id`, `aggregate_id`, `occurred_at`, and a
  versioned payload.
- Producers **MUST NOT** know who consumes their events.
- Consumers **MUST** be idempotent — they may receive the same event more
  than once.
- An event **MUST NOT** be relied upon for correctness of an in-process
  invariant. Invariants are protected by the application-service transaction;
  events are informational.

### 2.4 Data Flow Rules

- The frontend **MUST NEVER** access the database directly. Not Postgres,
  not Redis, not MinIO buckets.
- The frontend **MUST** communicate only via:
  1. REST API (`/api/v1/...`)
  2. WebSocket (`/ws/v1`)
  3. MQTT (future, only via the backend's MQTT bridge — never to a raw
     broker)
- The AI Engine **MUST NEVER** write directly to the database.
- Only the **backend** is allowed to persist business data to Postgres.
- The AI Engine **MAY** write transient artefacts (snapshots, frames,
  embeddings) to MinIO **only** through a backend-issued signed URL or a
  backend-mediated upload endpoint.

#### Approved data-flow diagram

```
┌──────────┐     REST / WebSocket     ┌──────────┐    SQL      ┌────────────┐
│ Frontend │ ───────────────────────► │ Backend  │ ──────────► │ PostgreSQL │
└──────────┘                          └─────┬────┘             └────────────┘
                                            │
                                            │ Cache / Pub-Sub
                                            ▼
                                       ┌────────┐
                                       │ Redis  │
                                       └────────┘
                                            ▲
                                            │ Events (EventBus)
┌──────────┐     HTTP / Events       ┌──────┴────┐    Signed URL    ┌───────┐
│ AI Engine│ ◄─────────────────────► │ Backend   │ ───────────────► │ MinIO │
└────┬─────┘                         └───────────┘                  └───────┘
     │  RTSP / RTMP / HTTP
     ▼
┌──────────┐
│ Cameras  │
└──────────┘
```

Any data flow not pictured above is **invalid** and **MUST** be refactored.

### 2.5 Module Isolation Rules

Each module is a **bounded context** under `backend/app/modules/<context>/`
and **MUST** be independent.

Initial modules:

- `product` (catalog)
- `inventory`
- `camera`
- `ai` (AI Engine integration surface inside the backend)
- `customer`
- `order` (sales)
- *(plus supporting contexts: `tenancy`, `identity`, `notification`,
  `audit`, `employee`)*

#### Hard rules

- **No direct cross-module database access.** A module **MUST NOT** read
  from or write to another module's tables. SQLAlchemy `relationship()`
  **MUST NOT** cross module boundaries. FK *columns* may cross, but
  navigation is performed via the owning module's repository.
- Cross-module communication is allowed **only** through:
  1. **Application services** with a published, typed interface.
  2. **Domain events** via the shared `EventBus`.
  3. **REST APIs** when one module truly needs to call another's HTTP
     surface (rare; for future inter-service splits).
- A module **MUST NOT** import from another module's `domain/` or
  `infrastructure/` packages.
- Each module **MUST** be deletable / replaceable as a unit. If removing one
  module would force changes in another module's domain code, the
  boundaries are wrong and **MUST** be fixed.

### 2.6 Database Rules

- **PostgreSQL is the only primary database.** All business state of record
  lives in Postgres.
- **Redis is only for cache and real-time / ephemeral state** — token
  revocation lists, rate-limit counters, queues, pub/sub, short-lived
  session data. Redis **MUST NOT** hold a single source of truth for any
  business entity.
- **MinIO (or its S3-compatible cloud equivalent) is only for file
  storage** — images, snapshots, clips, embeddings, report exports,
  uploaded CSVs. Binary blobs **MUST NOT** be stored in Postgres.
- **No business logic in the database.** Stored procedures, business
  triggers, and computed business columns are **forbidden**. Allowed
  database-side logic is limited to: integrity constraints (`CHECK`,
  `UNIQUE`, `FK`), audit timestamp triggers, and Postgres extensions used
  generically (e.g. `pgcrypto` for UUIDs, `pg_trgm` for search).
- Schema changes **MUST** be expressed as Alembic migrations and reviewed
  for destructive operations.
- All tenant-scoped queries **MUST** include `organization_id` in the
  predicate (see §2.8).

### 2.7 API Rules

- The REST API **MUST** be versioned: `/api/v1/...`. Breaking changes
  require a new major version path.
- **WebSocket MUST** be used for real-time updates (live detections,
  alerts, notification push). Polling REST endpoints to simulate real time
  is **forbidden**.
- Every REST response **MUST** follow the consistent response envelope:

  ```json
  {
    "success": true,
    "data": {},
    "message": "",
    "error": null
  }
  ```

  - `success` is a boolean — `true` for 2xx outcomes, `false` otherwise.
  - `data` carries the response payload (object or array). On error,
    `data` is `null`.
  - `message` is a short, human-readable string suitable for UI display.
  - `error`, on failures, is an object of the shape
    `{ "code": "ERR_CODE", "details": { ... } }`. On success, `error` is
    `null`.

- Every list endpoint **MUST** support the documented pagination,
  filtering, and sorting convention.
- Every mutating endpoint **MUST** accept (and may require, when retried)
  an `Idempotency-Key` header.
- The OpenAPI spec **MUST** be generated from code and kept current.

### 2.8 Security Rules

- **JWT authentication** is required for all protected endpoints.
  Anonymous access is allowed only for `/health`, `/ready`, login,
  password-reset, and explicitly whitelisted public endpoints.
- **Role-Based Access Control (RBAC)** governs every protected route.
  Every endpoint declares a required permission; missing declarations are
  a CI failure.
- **Multi-branch (and multi-tenant) isolation MUST be enforced at the
  query level.** Every tenant-scoped query includes `organization_id`
  (and `branch_id` where applicable) in the predicate. Frontend filters
  are advisory; backend filters are authoritative.
- **No sensitive data in frontend storage except the auth token.** No
  hashed passwords, no PII beyond what the UI is rendering at that moment,
  no JWT signing keys, no internal IDs that would enable enumeration.
  Tokens **MUST** be stored using the most restrictive storage available
  (HttpOnly cookie or in-memory) for the threat model in scope.
- All secrets **MUST** be sourced from environment variables or a secret
  manager — never committed to the repository.
- All inputs from external systems (HTTP, MQTT, file upload) **MUST** be
  validated at the system boundary.

### 2.9 Scalability Rules

The system **MUST** support, by design:

- **Multi-camera scaling** — adding cameras requires only configuration,
  not code changes.
- **Multi-branch architecture** — adding a branch does not degrade
  per-branch performance.
- **Horizontal backend scaling** — N backend instances behind a load
  balancer behave identically.
- **AI Engine separation onto GPU servers** — AI Engine and backend run on
  independent hosts, communicate over the network, and scale
  independently.
- **Stateless API design** — any backend instance can serve any request.
  No in-memory session, no sticky load balancing required for correctness
  (sticky may be used as an optimisation for WebSocket).
- **Background workloads** run on Celery workers that scale on queue
  depth, independently of the API.

---

## 3. Non-Functional Requirements

These NFRs are part of the contract. They are observable, testable, and
enforced via CI / staging benchmarks.

| Category | Requirement |
|----------|-------------|
| **Performance** | High-performance real-time processing. Per-camera detection pipeline runs at the camera's configured target FPS without sustained backlog. |
| **Latency** | End-to-end AI inference latency from frame capture to event published **SHOULD** be ≤ 1 s on reference hardware, and **MUST** be measured and reported in metrics. |
| **Fault tolerance** | Camera stream failures (drop, timeout, malformed frame) **MUST NOT** crash the AI Engine or backend. Reconnect with exponential backoff is mandatory. |
| **Horizontal scalability** | Doubling backend instances **MUST** approximately double API throughput, up to the database limit. No instance-affinity for correctness. |
| **Modular upgrades** | Replacing or upgrading one module (catalog, AI model, payment gateway) **MUST NOT** require changes in unrelated modules. |
| **Observability** | Every service emits structured JSON logs with `X-Request-ID`, Prometheus-style metrics, and (in Tier 2 deployments) OpenTelemetry traces. |
| **Backup & recovery** | Postgres and MinIO **MUST** be backed up daily; a documented restore procedure exists and is rehearsed quarterly. |
| **Security** | No `Critical` or `High` vulnerabilities in production images. Dependency scanning runs in CI. |

---

## 4. Technology Boundaries

These choices are **fixed**. Adding or replacing any of them requires a new
ADR and an amendment to this contract.

| Concern | Approved Technology | Forbidden alternatives in this codebase |
|---------|---------------------|------------------------------------------|
| **Backend HTTP / WebSocket** | **Python + FastAPI ONLY** | Django, Flask, Node.js, Go, Java, etc. |
| **Frontend** | **React (with TypeScript + Vite + Tailwind + Ant Design) ONLY** | Vue, Angular, Svelte, Next.js (SSR), etc. |
| **AI Engine** | **Python ONLY** | C++ inference servers as the primary, Triton-only deployments, etc. (Triton **MAY** be used *behind* the Python service if benchmarks demand it.) |
| **Primary OLTP database** | **PostgreSQL ONLY** | MySQL, MongoDB, SQL Server, Oracle, DynamoDB. |
| **Cache / Queue / Pub-Sub (in-memory)** | **Redis ONLY** | Memcached, in-process caches as shared state. |
| **Object storage** | **MinIO ONLY** (with S3 / GCS / Azure Blob as cloud-equivalent drop-ins via the S3 API) | Local filesystem mounts, `bytea` columns, ad-hoc FTP. |
| **Background jobs** | Celery (Python) on Redis (see ADR-010, ADR-014) | Custom thread pools, ad-hoc cron in containers. |
| **Reverse proxy / TLS** | Nginx | Apache, Traefik in production (Traefik allowed in dev). |
| **Container packaging** | Docker + Docker Compose / Kubernetes | Bare-metal deployments, OS-package installs. |

Any introduction of a new runtime dependency, framework, or storage system
that is not listed above **MUST** be preceded by an approved ADR.

---

## 5. Enforcement and Exceptions

This contract is enforced by:

1. **Code review** — reviewers reject PRs that violate any rule.
2. **CI gates** — lint, import-linting, type-checking, test coverage,
   security scanning. A failing gate blocks merge.
3. **Architecture review** for any PR introducing a new module, new
   external dependency, or new cross-context coupling.
4. **Quarterly audit** of the codebase against this contract by the Chief
   System Architect.

#### Exceptions

- An exception to any rule **MUST** be:
  - Documented in a new ADR under `docs/adr/`, and
  - Approved by the Chief System Architect, and
  - Time-boxed with a written removal plan.
- An "exception" without an ADR is a **violation**, not an exception.

---

## 6. Strict Rule

> Any future implementation that violates this Architecture Contract **MUST
> be considered INVALID** and **MUST be refactored** before being merged or,
> if already merged in error, in the very next iteration. There are no
> grandfathered violations.

The presence of working code is **not** a justification for keeping it. The
contract takes precedence over convenience, deadlines, and personal
preference.

---

## 7. Glossary

| Term | Meaning |
|------|---------|
| **Bounded Context** | A module that owns a coherent slice of the business model with its own ubiquitous language. |
| **Aggregate** | A cluster of domain objects treated as a single unit for data changes; protects its invariants. |
| **Domain Event** | An immutable record that something business-meaningful happened. |
| **Application Service** | A use-case orchestrator that coordinates repositories, domain objects, and external services within a single transaction boundary. |
| **Repository** | An abstraction over persistence; the domain talks to a repository interface, the infrastructure provides the implementation. |
| **Tenant** | An organisation using VisionMart. Every business row is scoped to a tenant. |
| **Branch** | A physical store location under a tenant. |
| **Stateless service** | A service whose correctness does not depend on any in-memory state surviving between requests. |
| **Idempotent** | An operation that, applied multiple times with the same input, produces the same observable result as applying it once. |

---

*This contract evolves only through an amendment PR that touches **only this
file** and is approved by the Chief System Architect. Any other change to it
is invalid.*
