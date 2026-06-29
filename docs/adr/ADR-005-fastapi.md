# ADR-005 — FastAPI as the backend HTTP framework

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

The backend exposes a REST API (ADR-012), a WebSocket gateway (ADR-013), and
internal HTTP endpoints to the AI Engine. We need a Python framework that:

- Is **async-first** — many endpoints fan out to DB, Redis, MinIO, and the AI
  Engine; blocking I/O would cap throughput.
- Has first-class **type hints** integration so request/response models are
  validated automatically.
- Produces an **OpenAPI** spec without extra effort (required by ADR-012).
- Supports **WebSocket** natively.
- Has a mature ecosystem for auth, middleware, and testing.

## Decision

Use **FastAPI** for the backend. Specifically:

- HTTP routes, WebSocket routes, and middleware all live under `backend/app/`.
- Pydantic v2 is used for request and response schemas (`schemas/`).
- Dependencies (DB session, current user, settings) are provided via FastAPI's
  `Depends()` system, wired through `backend/app/dependencies/providers.py`.
- The AI Engine is a separate FastAPI app on a separate port, with no shared
  process state.

## Consequences

**Positive**

- Native async means we can serve thousands of concurrent WebSocket clients
  per worker.
- Automatic OpenAPI generation keeps the public contract honest.
- Pydantic validation pushes input validation to the edge, satisfying the
  security-by-default principle.
- The DI system aligns naturally with Clean Architecture (ADR-001).

**Negative**

- Async code is contagious — accidental blocking calls (`time.sleep`,
  blocking DB drivers) silently degrade throughput. Mitigated by linting rules
  and code review checklists.
- The Pydantic-FastAPI version coupling forces us to track compatibility
  matrices on upgrades.

**Neutral**

- FastAPI is built on Starlette; if we ever need to drop FastAPI for any
  reason, Starlette would be the natural escape hatch.

## Alternatives Considered

- **Django / Django REST Framework** — Mature and batteries-included, but
  primarily synchronous and heavier. Async story is improving but not
  comparable to FastAPI for our workload mix. Rejected.
- **Flask** — Synchronous by default; would require ad-hoc patterns for async.
  Rejected.
- **Litestar** — Modern and async, comparable in spirit. Smaller community and
  less third-party material. Reconsider on a future major rewrite.
- **Go (Echo / Fiber) for the API layer** — Faster per-core but splits the
  stack across two languages and prevents code sharing with the AI Engine
  (which must remain Python). Rejected as primary; possible for an extracted
  ultra-hot path later.
