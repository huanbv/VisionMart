# ADR-003 — Modular Monolith as the deployment style

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart has many bounded contexts (ADR-002) and aims to be deployable in
environments ranging from a single laptop demo to a multi-region cluster. Two
deployment styles dominate the industry:

1. **Microservices** — each context is a separately deployed service.
2. **Monolith** — one deployable, one process.

Microservices solve scaling and team-autonomy problems we **do not yet have**
and impose operational costs (service discovery, distributed tracing, per-
service CI/CD, network reliability, schema versioning across the wire) that
would slow early delivery. A traditional monolith, on the other hand, tends
toward big-ball-of-mud over time without strong boundaries.

We need a style that gives us the *internal* modularity of microservices with
the *operational* simplicity of a single deployable.

## Decision

Adopt a **Modular Monolith**:

- **One deployable backend process** containing every bounded context.
- Each context lives in its own folder under `backend/app/modules/<context>/`
  and exposes a small, deliberate public surface (application services,
  domain events).
- **Cross-module communication is restricted** to two channels:
  1. Calling another context's published **application service** interface.
  2. Subscribing to another context's **domain events** via the EventBus
     (ADR-014).
- **SQLAlchemy `relationship()` may not cross module boundaries.** FK columns
  may, but the navigation is explicit (look up by ID through a repository).
- The **AI Engine** is already a separate process for resource-isolation
  reasons (GPU). That is not a microservice split — it is an independent
  deployable that the backend talks to over HTTP.

When a context demonstrably needs independent scaling, deployment cadence, or
a different runtime (e.g. a Go service for ultra-low-latency event
forwarding), we can extract it into its own process *with minimal code change*
because the internal boundaries are already in place.

## Consequences

**Positive**

- One CI pipeline, one Docker image, one deploy. Operations are simple.
- Refactors that span multiple contexts are still possible inside one
  repository.
- We retain the option to split into services later without rewriting domain
  code.

**Negative**

- Engineers must *self-police* the module boundaries; without lint/CI checks,
  the boundaries erode.
- A single bug in one module can affect availability of the whole process.

**Neutral**

- Database is shared (single Postgres). Per-module schemas are a future option
  if a context demands isolation.

## Alternatives Considered

- **Microservices from day one** — Rejected. Premature operational
  complexity; we have neither the team size nor the proven scaling pressure
  to justify it.
- **Plain monolith without module boundaries** — Rejected. Predictable
  decline into entanglement.
- **Service-per-context Kubernetes deployment** — Considered as a future
  state; codified as an *optional* evolution rather than a starting point.
