# VisionMart — Production Deployment, Cloud Architecture & CI/CD

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** `docs/07_DEPLOYMENT_PLAN.md`
> **Owner:** Lead DevOps & Infrastructure Architect
> **Status:** v1.0 — Ratified
> **Date:** 2026-06-30
>
> **Scope:** infrastructure, deployment, and DevOps **design** only.
> No code, no YAML, no Dockerfiles, no scripts. Where this document
> conflicts with implementation, this document wins.
>
> **Companion documents:**
> [Architecture Contract](ARCHITECTURE_CONTRACT.md) ·
> [System Design](SYSTEM_DESIGN.md) ·
> [Authentication](13_AUTHENTICATION.md) ·
> [AI Overview](20_AI_OVERVIEW.md) ·
> [Camera Manager](21_CAMERA_MANAGER.md) ·
> [Dashboard & Analytics](37_DASHBOARD.md) ·
> [Notification & Integration Hub](15_NOTIFICATION_CENTER.md) ·
> [ADR-007 Docker](adr/ADR-007-docker.md) ·
> [ADR-015 Cloud Deployment](adr/ADR-015-cloud-deployment.md)

---

# Production Architecture Overview

VisionMart runs in **two deployment tiers**, sharing the same images
and the same architecture ([ADR-015](adr/ADR-015-cloud-deployment.md)):

- **Tier 1 — Compose** (single-host / branch edge / small SaaS
  tenant): Docker Compose v2 on a VPS or branch server. One node
  hosts the whole platform with optional GPU.
- **Tier 2 — Kubernetes** (multi-node SaaS / multi-tenant cloud):
  the same images deployed across an HA control plane, with GPU node
  pools, regional read replicas, and external managed services where
  appropriate.

The **logical** architecture is identical in both tiers; only the
**runtime substrate** changes.

### High-level user / API path

```
[Users (browser / mobile)]
        │ HTTPS
        ▼
[CDN / Edge (optional, SaaS tier)]
        │
        ▼
[Nginx Reverse Proxy] ── TLS termination, rate limits, security headers
        │
        ▼
[Backend API (FastAPI replicas)]
        │
        ├─► [PostgreSQL primary]
        ├─► [PostgreSQL read replica]    (Tier 2)
        ├─► [Redis (cache + pub/sub)]
        ├─► [MinIO (object storage)]
        ├─► [Celery workers (named queues)]
        └─► [EventBus] ──► consumers
```

### High-level AI path

```
[Cameras (RTSP / RTSPS)]
        │
        ▼
[AI Engine — Stream Processor (per camera)]
        │ frame extraction, preprocessing
        ▼
[AI Engine — GPU Inference Pool]
        │ YOLOv8 + ByteTrack + recognition
        ▼
[AI Engine — Rule Engine + Publisher]
        │ AIEvent + optional Snapshot
        ▼
[Backend AI Event Gateway] ──► [EventBus] ──► consumers
                                            (Cart, Inventory, Analytics,
                                             Notification, Dashboard, Audit)
```

### Cardinal deployment rules

1. **The same images run in every environment.** Environment
   differences are configuration only — no per-environment branches,
   no per-environment Dockerfiles.
2. **No state in app images.** All durable state lives in Postgres,
   Redis, MinIO, or the secret manager.
3. **AI runs in its own service.** The backend never imports AI
   model code; the AI Engine never writes to Postgres directly
   ([AI Overview](20_AI_OVERVIEW.md), Architecture Contract §2.2).
4. **Stateless backend replicas.** Any pod / container can be killed
   at any time; sessions are reconstructible from Postgres + Redis.
5. **All public traffic is TLS-only.** HTTP is redirected to HTTPS at
   the edge and refused at the application boundary.

---

# Infrastructure Design

### Roles and separation of concerns

| Role | Responsibility | Why isolated |
|------|----------------|--------------|
| **Edge / Nginx** | TLS, rate limits, security headers, static asset serving. | Smallest blast radius; protects everything behind it. |
| **Backend API node(s)** | FastAPI replicas; sync HTTP + WebSocket. | Horizontally scalable, stateless. |
| **Background worker node(s)** | Celery for analytics roll-ups, notifications, integrations, partition maintenance. | Slow jobs don't impact API latency. |
| **GPU AI node(s)** | AI Engine: stream + inference + tracking + rules + publish. | GPU is expensive; isolating the workload allows targeted scaling. |
| **Database node** (primary) | Postgres 16, OLTP writes + reads. | Single source of truth; tuned independently. |
| **Database replica node(s)** | Read replica(s) for heavy analytics queries. | Protects OLTP latency. |
| **Cache / pub-sub node** | Redis 7 (cache + revocation lists + WebSocket pub/sub). | TTL'd ephemeral state; separated for resilience. |
| **Object storage node** | MinIO (snapshots, embeddings, model artefacts, exports). | Binary data must never touch Postgres. |
| **Observability stack** | Prometheus / Grafana / Loki (or vendor-equivalent). | Stays up even when the app is degraded. |
| **Edge / branch node** (optional) | Local AI Engine + small Redis spool; communicates upstream. | Survives WAN partitions; keeps AI local to camera bandwidth. |

### VPS vs Cloud split strategy

| Component | VPS (Tier 1) | Cloud / Kubernetes (Tier 2) |
|-----------|--------------|----------------------------|
| Edge / Nginx | On-host | Ingress controller (Nginx / Traefik) + managed LB |
| Backend API | Compose service | Deployment + HPA |
| Celery workers | Compose services per queue | Deployments per queue + KEDA |
| Postgres | Compose volume | Managed Postgres (RDS / CloudSQL / equivalent) **or** self-managed with HA |
| Redis | Compose volume | Managed Redis (single-AZ for cache; cluster mode for high traffic) |
| MinIO | Compose volume | S3-compatible object storage |
| GPU AI nodes | Same host (with GPU) or a dedicated GPU VPS | Dedicated GPU node pool with taints/tolerations |
| Observability | Compose Prometheus + Grafana | Managed observability stack (or self-hosted in cluster) |
| Secret manager | `.env` mounted from a restricted host directory | Cloud secret manager (AWS Secrets Manager / Vault / equivalent) |
| Backups | Cron + off-host copy | Provider-managed snapshots + S3 lifecycle |

### Network segmentation

- **Public segment:** Nginx, WebSocket gateway endpoints.
- **Application segment:** Backend API + Celery workers. Reachable
  only from Nginx and (in Tier 2) from internal load balancers.
- **AI segment:** AI Engine nodes. Reachable only from Backend
  (for control) and from cameras (for RTSP).
- **Data segment:** Postgres + Redis + MinIO. Reachable only from
  the application + AI segments on explicit ports.
- **Management segment:** SSH / cluster API / observability scraping.
  Restricted to operator IPs and bastions.

---

# Containerization Strategy

### Docker per service (one container, one role)

- **Backend API** image — FastAPI; runs Uvicorn workers.
- **Celery worker** image — same Python source as backend but
  entrypoint is Celery; deployed per queue (notifications,
  analytics, integrations, partition-maintenance, reports).
- **AI Engine** image — Python + ONNX Runtime + ByteTrack +
  preprocessing; CUDA-enabled variant for GPU nodes.
- **Nginx** image — Nginx 1.27-alpine with project config.
- **Postgres** image — Postgres 16-alpine (Tier 1); managed in Tier 2.
- **Redis** image — Redis 7-alpine (Tier 1); managed in Tier 2.
- **MinIO** image — pinned RELEASE tag.
- **Frontend** is built into static assets and served by Nginx.

### Image discipline

- One **base Python image** shared by backend, workers, and AI; size
  optimised via multi-stage builds.
- **Pinned tags** (no `latest`); SHA digests recorded in deployment
  manifests.
- **Distinct image tags per environment** are forbidden; promotion
  uses the same digest end-to-end.
- Images include a **non-root user**, **read-only root filesystem**
  where feasible, and a **healthcheck**.

### Service isolation

- One process per container; one container per replica.
- Cross-service communication is over the network only; no shared
  volumes for IPC.
- **Volumes** are only for true persistence (Postgres data, MinIO
  data); not for application state.

### Tier 1 — Docker Compose

- Single `compose` project encompasses the whole platform.
- Profile-based optional services (`gpu`, `observability`,
  `dev`) keep the file usable on small hosts.
- `depends_on` + healthchecks gate startup order.

### Tier 2 — Kubernetes

- One namespace per environment (and optionally per tenant for
  premium customers).
- **Deployments** for stateless services; **StatefulSets** for any
  self-hosted Postgres / MinIO / Redis instance.
- **HPA** for API + worker scaling on CPU + custom metrics;
  **KEDA** for queue-depth and GPU-utilisation scaling.
- **Resource requests/limits** mandatory on every container;
  **PodDisruptionBudgets** on user-facing services.
- **NetworkPolicies** enforce the segmentation described above.

---

# CI/CD Pipeline

### Branch strategy

- `main` — always deployable to **production**.
- `develop` — integration branch; deployed automatically to
  **staging** on every push.
- `feature/*`, `fix/*`, `refactor/*` — short-lived branches off
  `develop`; merged via PR with required checks.
- `hotfix/*` — branch off `main` for urgent fixes; merged into both
  `main` and `develop`.
- `release/*` (optional) — used for release stabilisation when the
  team is large; otherwise `main` is the release.

### Conventional Commits

- `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `test:`, `ci:`,
  `build:` (per the project architecture guidelines).
- Drives changelog generation and release notes.

### CI flow (per push / per PR)

```
[Developer push]
   │
   ▼
[GitHub Actions]
   │
   ├── Lint (Ruff / ESLint / Prettier / Stylelint)
   ├── Type-check (mypy / tsc --noEmit)
   ├── Unit tests (pytest + Vitest) with coverage gate
   ├── Integration tests (testcontainers: Postgres + Redis + MinIO)
   ├── Security scan (deps, secrets, SAST, container scan)
   ├── License check
   └── Build artefacts:
         - Backend image
         - Worker image (same source, different entrypoint)
         - AI Engine image (CPU + CUDA variants)
         - Frontend bundle
   │
   ▼
[Container Registry] (digest-pinned tags pushed)
   │
   ▼
[CD trigger by branch]
```

### CD flow

| Branch / event | Target | Strategy |
|----------------|--------|----------|
| Push to `develop` | Staging | Automatic; rolling update; smoke tests post-deploy. |
| Merge to `main` | Production | Automatic for low-risk services; **manual approval gate** for AI Engine, schema migrations, and infra changes. |
| Tag `vX.Y.Z` | Production release | Triggers changelog + release notes + image promotion. |
| `hotfix/*` merged into `main` | Production fast-path | Bypasses non-blocking checks but **never** the security or migration gates. |

### Deployment style

- **Rolling updates** as the default (zero downtime for stateless
  services).
- **Blue/green** as an option for the backend API during major
  cutovers (database-compatible across versions only).
- **Canary** for the AI Engine: a fraction of cameras routed to the
  new model registration first; metrics gating before full rollout.

### Migration discipline

- Alembic migrations run in a **dedicated step**, separately from
  the application rollout, and **before** new code goes live for
  additive changes.
- Migrations are **forward-compatible** with the previous app
  version (the app continues to work without the new column for one
  release cycle when possible).
- Destructive operations require an ADR and a documented
  back-out plan.

### Rollback strategy

- **Image rollback:** redeploy the previous digest. Fast; safe for
  any backwards-compatible change.
- **Database rollback:** prefer **forward fixes** over reversing a
  migration. Reversible migrations are paired with explicit
  `downgrade` only when the change is structural.
- **Feature flags:** non-breaking changes can be flag-gated so
  rollback is a flag flip rather than a redeploy.

---

# GPU AI Deployment

### Topology

- AI Engine workers run on **dedicated GPU nodes** (or
  GPU-equipped VPS in Tier 1).
- Backend and API workers run on **CPU nodes**; they never share
  a GPU with the engine.
- In Tier 2, GPU nodes form a **node pool** with taints; only AI
  Engine pods tolerate them.

### Allocation strategy

- One **per-camera worker** per camera handles ingestion + tracking
  + rules (mostly CPU + small GPU for preprocessing on supported
  hardware).
- One **per-GPU detector worker** owns micro-batched detection for a
  group of cameras assigned to that GPU
  ([Camera Manager §Frame Processing](21_CAMERA_MANAGER.md)).
- A **scheduler** assigns cameras to GPU nodes by **consistent
  hashing** on `camera_id`, weighted by current load (CPU%, GPU%,
  in-flight batches, drop counters).

### Model deployment pipeline

- Model artefacts (ONNX, calibration, metadata) live in **MinIO**
  under a tenant-segregated path. They are immutable; new versions
  publish new objects.
- A `ModelRegistration` row in Postgres pins the **active version
  per VisionPipeline** ([Camera Manager §AI Input](21_CAMERA_MANAGER.md)).
- The AI Engine, on start or on `ModelDeployed` signal, downloads
  the active artefact and warms it (load + benchmark + smoke
  detection).
- **Canary rollout:** new model registrations apply to a fraction of
  cameras first; metrics (latency, accuracy proxies, event rates)
  gate full rollout. Bad canaries auto-rollback to the previous
  registration.

### Frame distribution & load balancing

- Cameras are bound to GPU nodes by the scheduler at assignment
  time; they don't dynamically migrate on every frame.
- Within a node, the per-GPU detector queue is **micro-batched** with
  a time bound; lone frames dispatch without waiting.
- Heavy pipelines (face recognition, large-index product
  recognition) **MAY** be steered onto dedicated GPU pools.

### GPU node sizing guidance

- Target ~70 % steady-state GPU utilisation to absorb spikes /
  reconnect storms.
- Plan one GPU per ~16–32 cameras at 5 fps on the default pipeline
  mix (varies with model + image size); revalidate per tenant.

---

# Database Deployment

### Postgres setup

- **Postgres 16** with `pgcrypto` enabled.
- **Tier 1:** single Postgres container with a dedicated data
  volume, daily cron backups copied off-host.
- **Tier 2:** managed Postgres preferred; otherwise self-managed HA
  with synchronous replication.

### Replication

- **Streaming replication** to at least one **read replica** in
  Tier 2; backend's heavy analytics reads target the replica.
- Replication lag is **monitored**; time-sensitive reads fall back
  to the primary when lag exceeds budget.

### Connection management

- **PgBouncer** (transaction pooling) in front of Postgres for
  spiky workloads (especially Kubernetes with many backend pods).
- App-side pool sizes tuned conservatively; one pool per process.

### Migrations (Alembic)

- Migrations live in the repo and run in CI **before** code
  rollout in the same pipeline.
- Each migration is reviewed for **destructive operations** (drop
  column, drop table, rename) and gated by an ADR if destructive.
- **Online-safe patterns** are mandatory: add nullable column +
  backfill + flip not-null in three releases rather than one
  blocking migration.

### Backups

| What | How | Cadence | Retention |
|------|-----|---------|-----------|
| Logical dump (`pg_dump` / `pg_dumpall`) | Off-host copy | Daily | 30 days |
| Physical base backup + WAL archive | PITR to S3 / MinIO | Continuous (WAL) + weekly base | 30 days hot, 1 year cold |
| Pre-migration snapshot | Before any destructive migration | Per release | Until next migration |
| Quarterly restore drill | Restore latest base + WAL into staging | Quarterly | Records kept |

### High availability considerations

- **Primary + sync replica + async replica** is the target HA shape
  in Tier 2.
- **Automatic failover** via the managed service or a tool such as
  Patroni in self-managed environments.
- **Connection retry + idempotent writes** on the application
  side; outbox-backed publishes survive a brief failover.

---

# Redis Deployment

### Roles

- **Cache** — short-TTL hot reads (cart mirrors, camera health, KPI
  counters).
- **Token revocation lists** — short-lived; naturally TTL'd.
- **Pub/Sub** — cross-replica WebSocket fan-out.
- **Celery broker + result backend** (or RabbitMQ in larger
  deployments).

### Persistence

- **Cache instance:** RDB snapshots only (loss tolerable; rebuild
  on cold start).
- **Broker instance:** AOF + RDB; tighter durability so queued
  jobs survive a restart.
- **Separation:** in Tier 2, cache and broker are **separate
  instances** so noisy-neighbour patterns don't cross.

### Failover

- **Tier 1:** single Redis with persistent volume; tolerated for
  small deployments.
- **Tier 2:** **Redis Sentinel** (or cluster mode in very high
  traffic) with managed failover.
- App-side retries with backoff; consumers tolerate brief Redis
  outages.

### Memory optimisation

- Keys are **namespaced and TTL'd** consistently
  ([Dashboard §Redis optimisation](37_DASHBOARD.md)).
- `maxmemory` set with `allkeys-lru` policy on cache instance;
  broker uses `noeviction`.
- Per-tenant rate limits prevent a single tenant from filling the
  cache.

---

# Nginx & API Gateway

### Reverse proxy

- TLS termination (TLS 1.2+, prefer TLS 1.3).
- Strong cipher suites; HSTS preload-eligible.
- Security headers: HSTS, CSP, X-Content-Type-Options,
  Referrer-Policy, X-Frame-Options.
- Request size caps; timeout caps tuned per endpoint class.

### Load balancing

- Tier 1: Nginx upstream blocks load-balance API replicas on the
  same host.
- Tier 2: ingress controller (Nginx / Traefik) + cluster service +
  managed external LB.
- **WebSocket connections** use a sticky LB; HTTP requests can be
  round-robin.

### Rate limiting

- Per-IP and per-token rate limits at the edge, stricter on
  `/auth/*`, mutating endpoints, and report endpoints.
- Returning `429` with a `Retry-After`.
- Per-tenant budgets layered above per-IP to defend against a noisy
  tenant.

### TLS / certificate management

- ACME (Let's Encrypt) for public certs; managed certificate
  service in Tier 2.
- **Wildcard cert** for `*.thehuan.com` so per-tenant subdomains
  are zero-config.
- Automated renewal with monitored expiry.

### API version routing

- `/api/v1/...` is the v1 contract surface.
- `/api/v2/...` reserved for future contracts; both **MAY** coexist
  through a deprecation window.
- The frontend reads the API version from configuration; mixed
  versions in one client are forbidden.
- WebSocket endpoints follow the same versioning rules.

---

# Monitoring & Observability

### Stack (concept; vendor-substitutable)

- **Metrics:** Prometheus scraping every service; Grafana for
  dashboards.
- **Logs:** Loki (or equivalent) for structured JSON logs.
- **Traces:** OpenTelemetry-style traces with `correlation_id`
  propagation, exported to Jaeger / Tempo / vendor.
- **Synthetic checks:** external probes for login, dashboard load,
  AI event ingestion, webhook delivery.

### Metrics taxonomy

| Domain | Examples |
|--------|----------|
| **Host / runtime** | CPU, memory, disk, network, GPU utilisation, GPU memory, NVDEC sessions, container restarts. |
| **API** | Requests per second per route, p50/p95/p99 latency, error rates per status class, in-flight requests, WebSocket connections. |
| **DB** | Connections, transactions per second, slow queries, replication lag, vacuum activity, cache hit ratio. |
| **Redis** | Hit ratio, evictions, pub/sub channel counts, key TTL distributions. |
| **Event bus** | Events produced/consumed per type per tenant per minute; queue depths; DLQ size. |
| **Cameras** | Status counts, effective vs target FPS, drop rate, reconnects. |
| **AI pipeline** | Per-stage latency histograms, per-pipeline event rates, detector batch sizes, model version in use. |
| **Cart / Orders / Inventory** | Operations per second, error rates, oversell attempts, abandonment rates. |
| **Notifications** | Sent / failed per channel, queue depth, SLA breaches. |
| **Webhooks** | Delivery success / failure per subscription, retry counts, DLQ growth. |

### Dashboards

- **Operator overview** (per tenant): one screen with health of API,
  AI, cameras, queues, alerts.
- **Platform overview** (super_admin): all tenants by SLO health.
- **Per-tenant SLO dashboard:** event latency, dashboard latency,
  webhook deliverability, AI pipeline health.

### Alerting

- Alert rules graded by severity (Critical / High / Medium / Low),
  mirroring the [Notification Center](15_NOTIFICATION_CENTER.md)
  priorities.
- Alerts route to the operator on-call channel; integration with
  Pager Duty / Opsgenie via webhook in production.
- **No flapping:** every alert has hysteresis and a minimum
  duration.

---

# Logging System

### Strategy

- **Structured JSON logs** from every service; no `print()` in
  production code.
- Every log line carries `service`, `version`, `level`, `timestamp`,
  `correlation_id`, `organization_id` (when applicable),
  `branch_id` (when applicable), `event_id` (when applicable).
- Stack traces are emitted as multi-line fields, never raw stdout.

### Log levels

- **DEBUG** — disabled in production by default; togglable per
  service via configuration without redeploy.
- **INFO** — normal lifecycle, requests served, events processed.
- **WARN** — degraded but functioning (retry, fallback, low
  confidence).
- **ERROR** — operation failed; user impact possible.
- **CRITICAL** — service or data at risk; pages on-call.

### Storage strategy

- Logs ship to the central log store (Loki / vendor) with a
  bounded hot retention (e.g. 14 days) and a longer cold retention
  in object storage.
- Security-relevant logs (`auth.*`, `authz.*`, audit) ship to the
  same store and are also written to the `AuditLog` table for
  immutable retention.

### Debugging pipeline

- A `correlation_id` propagates from Nginx → backend → workers →
  AI Engine → outgoing webhooks; one search recovers the entire
  thread of a user action or an AI event.
- Operators can pivot from a notification or an alert to the
  underlying logs in one click.

### Scrubbing

- Secrets, tokens, passwords, payment data, and biometric data are
  **scrubbed at the source** (formatter rule + linted patterns).
- PII appears only when explicitly required and is masked in logs.

---

# Backup & Recovery

### What gets backed up

| Asset | Method | Cadence | RPO target |
|-------|--------|---------|------------|
| Postgres (logical) | `pg_dump` to off-host storage | Daily | 24 h |
| Postgres (PITR) | Base backup + WAL archive | Continuous (WAL); base weekly | ≤ 5 min |
| MinIO (snapshots, embeddings, models, exports) | Object versioning + lifecycle replication to a second bucket / region | Continuous | seconds |
| Redis (cache) | RDB snapshot | Hourly (not critical) | acceptable: minutes |
| Redis (broker) | AOF + RDB | Continuous | seconds |
| AI models | Immutable objects in MinIO + checksums recorded in `ModelRegistration` | On publish | n/a |
| Camera configurations | Postgres backups cover them | per DB cadence | per DB |
| App configuration / IaC | Git (single source of truth) | per push | n/a |
| Secrets | Secret manager's own backup / vault snapshots | Per provider | provider |
| Audit log | Postgres backups + later archive to object lock | per DB | per DB |

### Disaster recovery plan

- **RTO** (time to recover): production target ≤ 1 h for backend +
  database; ≤ 2 h for full AI restoration.
- **RPO** (data loss tolerated): ≤ 5 minutes for OLTP via PITR;
  seconds for object storage.
- **Documented runbook** with step-by-step recovery, contact list,
  rollback decision tree.
- **Quarterly DR drills** — restore from backups into an isolated
  environment; results recorded.
- **Cross-region option** for SaaS: secondary region with async
  replication for premium tenants.

---

# Scaling Strategy

### Horizontal scaling

- **Backend API**: stateless; scale on CPU + p95 latency + WebSocket
  count. HPA in Tier 2.
- **Celery workers**: scale per queue on depth and consumer lag.
  KEDA in Tier 2.
- **AI Engine workers**: scale per GPU node pool on GPU utilisation
  + event-publish queue depth.

### Load balancing

- Edge load balancer for north-south traffic.
- Internal service-to-service via the cluster's service mesh /
  Kubernetes service abstraction (or Compose's network in Tier 1).
- WebSocket sticky LB; HTTP round-robin.

### Vertical scaling

- Used only for **Postgres primary** within reason; otherwise the
  default answer is horizontal.

### Multi-region (future-ready)

- Region-local Postgres + Redis + MinIO per region.
- Tenants pinned to a **home region**; cross-region failover plan
  documented.
- Event delivery and webhook delivery are region-aware (avoid
  cross-region chatter for latency-sensitive flows).

### Cost shaping

- Per-tenant resource budgets enforced at the application layer.
- Spot / preemptible GPU nodes are acceptable for analytics-heavy
  workloads; the live AI tier prefers reserved capacity.

---

# Security in Production

### Transport security

- **TLS everywhere**; HSTS; HTTP redirects to HTTPS.
- mTLS optional between internal services in Tier 2.

### Identity / JWT

- Asymmetric signing (RS256 / EdDSA) with **JWKS rotation** and
  `kid` ([Authentication §Token Strategy](13_AUTHENTICATION.md#token-strategy)).
- Per-environment **distinct issuers and audiences**; production
  tokens cannot be verified by staging keys and vice versa.

### Firewall / network

- Default-deny ingress; explicit ports per role.
- AI Engine nodes can reach Backend + Cameras + MinIO only.
- Database segment reachable only from app + AI segments on
  Postgres / Redis / MinIO ports.
- Management segment locked down to bastion / VPN.

### Rate limiting

- Per-IP, per-token, per-tenant at the edge and at the application
  layer.
- Burst-friendly defaults; spikes shed gracefully with `429`.

### Secret management

- **No secrets in source.** `.env` files for Tier 1 are owned by
  ops, mounted read-only.
- **Secret manager** (Vault / AWS Secrets Manager / equivalent) for
  Tier 2.
- **Rotation** documented and automated for: DB credentials, Redis
  password, MinIO keys, JWT signing keys, webhook HMAC secrets,
  external integration keys.
- Application reads via `pydantic-settings`; **never** logs the
  value.

### Container hardening

- Non-root user, read-only root filesystem where possible,
  capability drop, seccomp default-deny, no host networking.
- Image vulnerability scanning gates promotion to production.

### Backups + audit + compliance

- Backups encrypted at rest.
- Audit log + access logs retained per regulatory floor.
- DPAs and processor declarations available for tenants who require
  them.

---

# Environment Strategy

### Environments

| Env | Purpose | Data | Promotion source |
|-----|---------|------|------------------|
| **Local development** | Per-developer | Ephemeral, fixture-loaded | n/a |
| **CI ephemeral** | Per CI run | Spun up with testcontainers per run | n/a |
| **Staging** | Pre-production validation; integration partner sandbox | Synthetic + opt-in subset of production-like data | Auto from `develop` |
| **Production** | Customer-facing | Real | Manual or auto from `main` (gated) |
| **Demo** (optional) | Sales / training | Curated demo dataset; isolated tenant | Tagged release |
| **DR / chaos** | Drill recoveries | Restore from production backups into an isolated environment | On schedule |

### Promotion flow

```
[feature/*] ── PR ──► [develop] ── auto deploy ──► [staging] ──► smoke + e2e tests
                                                       │
                                                  manual sign-off
                                                       │
                                                       ▼
                                                    [main]
                                                       │
                                                  auto deploy (gated)
                                                       │
                                                       ▼
                                                  [production]
```

### Configuration discipline

- **One Settings schema** ([Architecture Contract §3](ARCHITECTURE_CONTRACT.md));
  every environment sets values via environment variables.
- Production secrets **never** appear in staging; staging secrets
  **never** appear in production.
- **Feature flags** scope to environment.

---

# Deployment Topology

### Layered view

```
┌──────────────────────────── Client Layer ─────────────────────────────┐
│ Browser (SPA) · Cashier UI · Branch Dashboard · (Future) Mobile apps  │
└─────────────────────────────────┬─────────────────────────────────────┘
                                  │ HTTPS · WebSocket · (Future) WebRTC
┌─────────────────────────────────▼─────────────────────────────────────┐
│                          Edge / Gateway Layer                          │
│      Nginx (TLS, rate-limits, security headers, static assets)         │
└─────────────────────────────────┬─────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼─────────────────────────────────────┐
│                              API Layer                                 │
│            Backend (FastAPI replicas) · WebSocket gateway              │
└────────────┬────────────┬────────────────────────┬────────────────────┘
             │            │                        │
             │            │                        │
┌────────────▼─┐ ┌────────▼─────────┐ ┌────────────▼────────────┐
│  Event Layer │ │  Worker Layer    │ │  Integration Layer       │
│  In-memory   │ │  Celery queues:  │ │  Webhook deliverer       │
│  EventBus +  │ │  notifications,  │ │  Inbound integration API │
│  Redis pub/  │ │  analytics,      │ │  AI Event Gateway        │
│  sub         │ │  integrations,   │ │                          │
│              │ │  partitions,     │ │                          │
│              │ │  reports         │ │                          │
└────┬─────────┘ └──────┬───────────┘ └────────────┬─────────────┘
     │                  │                          │
     │                  │                          │
┌────▼──────────────────▼──────────────────────────▼──────────────────┐
│                              AI Layer                                 │
│   AI Engine nodes (CPU + GPU) · Stream processors · Detector pools    │
└──────────┬───────────────────────────────────────────────────────────┘
           │ AIEvent + Snapshot
           │
┌──────────▼───────────────────────────────────────────────────────────┐
│                            Data Layer                                  │
│ PostgreSQL primary · read replica(s) · Redis (cache + pub/sub)         │
└──────────┬───────────────────────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────────────────┐
│                          Storage Layer                                 │
│           MinIO / S3 · Cold archive · Backups · Model registry         │
└────────────────────────────────────────────────────────────────────────┘
```

### Camera path

```
[Cameras (RTSP / RTSPS)]
           │
           ▼
[AI Layer — per-camera workers]
           │
           ▼
[AI Layer — GPU detector pools]
           │ AIEvent + optional Snapshot
           ▼
[Integration Layer — AI Event Gateway]
           │
           ▼
[Event Layer → consumers]
```

---

# Failure Handling

| Failure | Containment | Recovery |
|---------|-------------|----------|
| **Backend pod crash** | Load balancer routes around it; in-flight requests retry idempotently. | Replica restarted by orchestrator; no manual action. |
| **Worker crash** | Queue redelivers in-flight messages on visibility timeout; consumers idempotent. | Replica restarted; backlog drains. |
| **Postgres primary failure** | App pauses writes briefly; reads can shift to replica if configured. | Managed failover (or Patroni) promotes the replica; app reconnects automatically. |
| **Postgres replica lag** | Time-sensitive reads route to primary; analytics reads continue with the stale replica when tolerable. | Lag resolves; routing flips back. |
| **Redis outage (cache)** | Hot reads fall back to Postgres; latency degrades but correctness holds. | Redis restarts; cache warms on next traffic. |
| **Redis outage (broker)** | Producers buffer briefly; if extended, jobs spool to a fallback or fail-fast with retry. | Broker restored; pending jobs processed. |
| **MinIO outage** | Snapshot uploads spool to local disk on the AI Engine with bounded budget; signed-URL downloads fail-soft with retry. | MinIO restored; spool flushes. |
| **AI Engine node failure** | Scheduler reassigns affected cameras to surviving nodes (consistent hashing). | Operator (or HPA) adds capacity; affected AI features auto-resume. |
| **GPU failure** | Driver / model healthcheck fails; node taken out of the pool. | Hardware replaced or node cordoned; cameras reassigned. |
| **Camera disconnect** | Per-camera worker enters backoff reconnect; status → `degraded`/`offline`. | Stream restored or operator intervention. |
| **Network partition between AI Engine and Backend** | AI Engine spools events locally up to bounded budget; backend queues continue. | Connectivity restored; spool flushes. |
| **Disk pressure on a node** | Application-level circuit breakers (spool budgets, log rotation) prevent OOM. | Operator clears pressure; service auto-recovers. |
| **Webhook subscriber down** | Retries with backoff; eventually DLQ. | Subscriber recovers; operator re-drives DLQ items. |
| **External integration credential rotation needed** | Service-account API key rotated; integration switches mid-window. | Old key revoked after grace; affected subscriptions notified. |
| **Region outage (multi-region tier)** | Tenants in the failed region fail over to standby region; RTO/RPO per documented SLO. | Region restored; rebalance scheduled. |

### Cardinal degradation rules

- **AI failure ≠ retail failure.** POS, inventory, dashboard
  business operations continue regardless of AI health.
- **Analytics failure ≠ transactional failure.** Carts, orders, and
  payments are independent of dashboard / aggregate health.
- **Webhook failure ≠ customer impact.** External integrations are
  best-effort with retries; the internal store of truth remains
  consistent.

---

# Future Improvements

### Platform

- **Service mesh** (Istio / Linkerd) for mTLS, retries, and policy
  in Tier 2.
- **GitOps** rollout (Argo CD / Flux) so the cluster state is the
  repo state.
- **Per-tenant namespaces** for premium isolation; eventual
  per-tenant database options.
- **Multi-region active/active** for SaaS, with conflict-free
  designs in catalog, customer, and audit.

### AI infrastructure

- **Spot GPU bursts** for non-real-time pipelines (training feedback,
  re-aggregation).
- **Model A/B testing** infrastructure with shadow traffic and
  auto-rollback on metric regression.
- **On-camera AI** offload where supported, with the engine running
  a thinner pipeline.

### Data

- **Managed Postgres + read replicas** in every region.
- **Columnar warehouse** (DuckLake / Snowflake) for very large
  analytical workloads.
- **Object-lock on audit and security snapshots** for tamper-evident
  retention.

### Observability

- **eBPF-based profiling** in production with tight safety bounds.
- **Per-tenant SLO dashboards** surfaced to tenant admins.
- **Auto-investigation** that, on SLO breach, surfaces the slow
  paths with correlation_ids and log slices.

### Operations

- **Self-service tenant provisioning** (create org, seed roles,
  default branches).
- **Per-tenant runbook bundle** generated from configuration.
- **Game days** simulating GPU loss, region loss, broker loss
  before customers ever feel them.

### Anti-goals (deliberately not on the plan)

- Per-environment Dockerfiles.
- Pet servers — every host is cattle in Tier 2; Tier 1 hosts are
  reproducible from IaC + compose project.
- Long-lived production access for developers without break-glass
  audit.
- Shared GPU between AI inference and ad-hoc data-science
  experimentation.
- Custom orchestrator code — we use Compose or Kubernetes, never a
  bespoke deploy daemon.

---

*This document is the canonical Production Deployment, Cloud
Architecture, and CI/CD design. Any change to deployment topology,
environments, scaling, or DR strategy requires a PR that updates
**only this file** (and, when needed, an ADR explaining the
rationale).*
