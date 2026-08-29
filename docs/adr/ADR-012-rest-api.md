# ADR-012 — REST + JSON as the primary public API style

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart's API will be consumed by:

- The first-party web frontend.
- A future mobile app.
- Third-party integrators (POS hardware, ERP systems, analytics tools).
- Internal services within the modular monolith for inter-context calls (a
  smaller, internal subset).

We need an API style that is **familiar, debuggable, cacheable, well-tooled,
and easy to version**. Most third-party retail integrators expect REST and
JSON.

## Decision

Standardise on **REST over HTTPS with JSON bodies** as the primary public API
style, served by FastAPI (ADR-005).

Specifically:

- **Versioned base path:** `/api/v1/...`. Breaking changes require a new major
  version path.
- **Resource-oriented URLs**, plural nouns, standard verbs (`GET`, `POST`,
  `PATCH`, `DELETE`). RPC-style endpoints are allowed only when they cannot
  be expressed as a resource operation.
- **OpenAPI 3** spec auto-generated from the code; Swagger UI mounted in
  non-production and permission-gated in production.
- **Consistent error envelope** — `{ "code": "...", "message": "...",
  "details": {...} }` (story `VM-API-03`).
- **Pagination, filtering, sorting** follow one documented convention across
  every list endpoint (story `VM-API-04`).
- **Authentication** via JWT bearer tokens (ADR-003 / `VM-AUTH-03`); API keys
  for service accounts.
- **Rate limiting** per token and per IP at the gateway (`VM-API-05`).
- **Idempotency-Key** header supported on every mutating endpoint that can be
  retried (`VM-API-06`).
- Real-time push uses **WebSocket** (ADR-013), not REST polling.

## Consequences

**Positive**

- Lowest-common-denominator integration story; works in browsers, mobile,
  CLI, and from any language.
- OpenAPI lets us generate typed clients for the frontend and integration
  partners.
- Caching, observability, and CDN behaviour follow standard HTTP rules.

**Negative**

- REST is not optimal for highly stateful, low-latency, push-based flows —
  but that is what WebSocket is for (ADR-013).
- Over-fetching / under-fetching is possible for clients that need
  cherry-picked fields. Acceptable for v1; we may layer GraphQL later if
  evidence accumulates.

**Neutral**

- The internal cross-module API (Python-to-Python) is **not** REST — it uses
  direct application-service calls in-process (ADR-003). REST is the
  **boundary** contract.

## Alternatives Considered

- **GraphQL** — Excellent for client-driven field selection, but adds
  schema-management complexity and harder authorization story for our
  multi-tenant model. Rejected for v1; reconsider as an additional surface.
- **gRPC** — Faster for service-to-service, but poor browser story without a
  proxy. Considered for *internal* AI-Engine ↔ backend traffic if benchmarks
  justify it; out of scope for v1's public API.
- **JSON-RPC** — Less tooling, smaller ecosystem. Rejected.
- **SOAP / XML** — Not in 2026. Rejected.
