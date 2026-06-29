# ADR-001 — Adopt Clean Architecture

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart must remain useful and modifiable for 5+ years across multiple
deployment targets (single-node Docker, multi-node Kubernetes, edge AI nodes).
The codebase will be touched by backend developers, AI engineers, and
infrastructure engineers concurrently. Two failure modes are common in projects
of this size:

1. Business rules become entangled with the HTTP framework, the ORM, or the
   message broker. Swapping any of them later requires a rewrite.
2. Testing requires a full Postgres + Redis + RTSP source to run, so tests are
   slow and rarely run locally.

We need an architecture style that decouples business rules from frameworks and
keeps the most valuable code (domain logic) testable in isolation.

## Decision

Adopt **Clean Architecture** as the layering policy for the backend:

- Layers from innermost to outermost: **Domain → Application → Infrastructure /
  API**.
- Dependencies always point **inward**. The domain layer imports *nothing* from
  frameworks (no FastAPI, no SQLAlchemy, no Pydantic).
- Concrete implementations (repositories, gateways, integrations) live in
  `infrastructure/`. The application layer talks to them via abstract
  interfaces declared near the domain.
- The HTTP/API layer is a thin shell that translates requests and responses;
  it owns no business logic.

The layout is documented in `.github/copilot-instructions.md` §8.

## Consequences

**Positive**

- Domain logic is unit-testable without spinning up a database.
- Swapping infrastructure components (e.g. SQLAlchemy → another ORM, FastAPI →
  another framework) is a localised change.
- New engineers can read the domain layer to understand "what the system does"
  without learning the entire stack.

**Negative**

- More files and indirection for simple CRUD features, which can feel
  ceremonial early on.
- Requires discipline to keep frameworks out of the domain. CI must enforce
  this with import linting.

**Neutral**

- Mirrors patterns familiar to many backend engineers; onboarding cost is low
  for senior hires but slightly higher for juniors.

## Alternatives Considered

- **Layered (traditional N-tier) architecture without dependency inversion** —
  Faster to scaffold but quickly leaks ORM models into HTTP responses and makes
  later refactoring expensive. Rejected.
- **Hexagonal (Ports & Adapters) directly** — Conceptually similar to Clean
  Architecture; we keep the Clean Architecture terminology because it is more
  widely recognised by the team. The two styles are largely interchangeable in
  practice.
- **Transaction Script / minimal abstraction** — Acceptable for tiny CRUD
  services, but VisionMart has long-lived business invariants (carts,
  inventory reservations, audit trails) that benefit from a domain model.
  Rejected.
