# ADR-002 — Adopt Domain Driven Design

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart is not a single-purpose CRUD app. It spans many distinct business
sub-domains — identity, tenancy, catalog, inventory, sales, cameras, AI
pipelines, analytics, notifications, audit. These sub-domains evolve at
different speeds and have different owners. A single shared data model would
become a contention point: any change to "Customer" would touch sales, vision,
and analytics simultaneously.

We need a method for **structuring** the codebase that mirrors how the business
actually thinks about its sub-problems, and for **defining boundaries** so
parallel teams do not collide.

## Decision

Adopt **Domain Driven Design (DDD)**, specifically:

- **Bounded Contexts** as the unit of modular decomposition. Each context
  lives under `backend/app/modules/<context>/` and is internally complete
  (`api`, `application`, `domain`, `infrastructure`, `schemas`).
- **Aggregates** own their invariants. Cross-aggregate consistency is achieved
  via domain events, not via in-process transactions across modules.
- **Ubiquitous Language** per context. The same English word may mean different
  things in `sales` and `inventory` — that is allowed and intentional.
- **Anti-Corruption Layer** when integrating with external systems (payment
  gateways, MQTT devices, third-party AI models): translation happens at the
  boundary so external concepts do not leak into the domain.

## Consequences

**Positive**

- Teams can own a bounded context end-to-end with minimal coordination.
- Each context can be extracted into its own service later (see ADR-003 and
  ADR-014) without rewriting business logic.
- Domain models stay focused; no "God object" for Customer or Product.

**Negative**

- Some concepts get represented twice (e.g. a slim `CustomerSnapshot` in
  `sales` mirrors fields from the canonical `Customer` in `customer`). The team
  must accept this duplication as the price of decoupling.
- Requires deliberate context mapping discussions during planning.

**Neutral**

- Increases the importance of writing down decisions (this ADR collection
  exists partly to make that easy).

## Alternatives Considered

- **Single shared domain model** — Simpler at first; fatal at scale.
  Rejected.
- **Microservices from day one** — DDD-style decomposition without the
  operational overhead. We prefer to ship as a modular monolith (ADR-003) and
  split later only where measurement shows it is necessary.
- **CRUD-only with no domain layer** — Insufficient for the invariants
  VisionMart needs (cart reservation, idempotent payment, audit chains).
  Rejected.
