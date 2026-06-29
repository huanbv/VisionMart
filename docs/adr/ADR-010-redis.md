# ADR-010 — Redis for cache, queues, and rate limiting

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart has several cross-cutting needs that do not belong in Postgres
(ADR-004):

- **Hot caching** of resolved permissions, configuration, and frequently read
  lookups.
- **Background job queue + result backend** for Celery (reports, exports, AI
  batch jobs).
- **Distributed rate limiting** at the API and at the auth endpoints.
- **Short-lived session / refresh-token revocation lists** that must be
  invalidated within seconds across multiple backend instances.
- **Pub/sub channel** for fan-out events to WebSocket workers (ADR-013).

Bolting all of this onto Postgres would multiply database load and create
contention with OLTP traffic.

## Decision

Adopt **Redis 7** as the in-memory data store for cache, queue broker, and
ephemeral coordination.

- One Redis instance per environment (managed equivalents — ElastiCache,
  Memorystore, Azure Cache — are first-class options).
- Logical separation by **Redis databases** or **key prefixes**:
  - `cache:*` — generic key-value cache
  - `celery:*` — Celery broker + result backend
  - `ratelimit:*` — sliding-window counters
  - `auth:*` — token revocation lists, login attempt counters
  - `pubsub:*` — fan-out channels
- Persistence is **AOF (append-only file)** on a 1-second fsync in production.
- All TTLs are explicit; no key may live forever unless it represents a
  configuration value with a documented invalidation path.

## Consequences

**Positive**

- One operational dependency covers many needs.
- Sub-millisecond reads remove a class of latency complaints.
- Celery + Redis is a well-trodden combination.
- Managed Redis is universally available across clouds.

**Negative**

- Redis is single-threaded per shard — extremely large workloads need Redis
  Cluster, which adds complexity.
- Memory-only storage means a crash without AOF loses ephemeral state.
  Documented and acceptable for the use cases listed.

**Neutral**

- We deliberately avoid relying on Redis for **business state** that must
  survive a Redis outage. Postgres remains the system of record.

## Alternatives Considered

- **Memcached** — Cache only; no queue, no pub/sub, no scripting. Rejected.
- **RabbitMQ for Celery + Postgres for cache** — Two extra moving parts.
  Rejected for v1; reconsider as part of ADR-014 broker selection.
- **In-process LRU cache** — Insufficient; we run multiple backend instances
  and they must share invalidation.
- **DragonflyDB / KeyDB** — Drop-in compatible. We will adopt if Redis hits
  a hard limit; until then, Redis is the default for ecosystem and tooling
  reasons.
