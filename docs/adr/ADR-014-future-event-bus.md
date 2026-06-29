# ADR-014 — Pluggable EventBus, in-memory now, broker later

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

Bounded contexts (ADR-002) inside the modular monolith (ADR-003) need to
communicate *asynchronously* without depending on each other's internals.
Examples:

- `sales` publishes `OrderPaid` → `inventory` decrements stock, `notification`
  sends a receipt, `analytics` increments KPIs.
- `ai-core` publishes `ProductPickedUp` → `sales` adds it to the shopper's
  cart.
- `camera` publishes `CameraWentOffline` → `notification` alerts the duty
  manager.

Today, with everything in one process, a real broker would be premature
infrastructure. But we *will* need one when:

- The AI Engine becomes physically distant from the backend.
- We split a bounded context into its own service.
- Multiple backend instances must observe the same events.

We need an abstraction that works **today** with zero extra infrastructure
and can be **swapped** to a real broker tomorrow without changing publisher or
subscriber code.

## Decision

Introduce a single **`EventBus` interface** in `backend/app/core/events/`.
Provide an **`InMemoryEventBus`** for v1.0 and design it so swapping in a
broker is a configuration change, not a code change.

Rules:

- Every cross-context message is a **`DomainEvent`** dataclass with at minimum
  `event_id`, `aggregate_id`, `occurred_at`, and a typed payload.
- Publishers depend on the `EventBus` interface only.
- Subscribers register handlers at startup via the DI container.
- The in-memory implementation:
  - Dispatches handlers concurrently via `asyncio.gather`.
  - Catches and logs handler failures so one failure does not poison the
    publisher.
  - Is **not** durable. Events lost on crash are acceptable in v1 for the
    handlers that use it (notifications, analytics, cache invalidation).
- For invariants that **must not** be lost (e.g. `OrderPaid` → stock decrement),
  the application service performs the work **transactionally in-process** and
  publishes the event afterwards. The event is informational; correctness does
  not depend on its delivery.

The future broker is left **deliberately open**. We will choose between
**Redis Streams**, **NATS JetStream**, **RabbitMQ**, or **Kafka** when a real
trigger appears (multi-process consumers, ordering / replay requirements,
cross-region fan-out). The selection will be a new ADR.

## Consequences

**Positive**

- Domain code is written *today* in the style we will need *tomorrow* —
  publishing events, not making direct cross-module calls.
- No premature broker dependency in v1.
- The extraction of a bounded context into its own service is mostly a
  matter of running the same handlers behind a broker subscriber.

**Negative**

- In-memory events are not durable. Engineers must understand which handlers
  may safely tolerate loss and which may not. This is documented in the
  domain-event catalogue.
- The interface must be designed conservatively from day one — adding
  required fields after the fact is painful.

**Neutral**

- Domain events are an *addition* to the application-service contract, not a
  replacement. Synchronous use cases keep returning typed results.

## Alternatives Considered

- **Start with a real broker on day one** — Operational overhead with no
  proportional benefit for v1. Rejected.
- **Direct cross-module calls only** — Recreates the entanglement we are
  trying to avoid. Rejected.
- **Celery as the event bus** — Works, but conflates "background job" with
  "domain event" and pushes everything through Redis. We keep Celery for
  background *jobs* and the EventBus for domain *events* — different
  semantics, different abstractions.
- **A library like `python-eventbus`** — Most are tiny wrappers that we
  would outgrow. Owning our minimal interface is cheaper.
