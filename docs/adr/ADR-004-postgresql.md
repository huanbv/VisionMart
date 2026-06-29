# ADR-004 — PostgreSQL as the primary OLTP store

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart needs a transactional store with strong guarantees for:

- Multi-tenant retail data (orders, payments, inventory reservations).
- Mixed workload — small frequent writes (detections, audit logs) and complex
  analytical reads (dashboards, reports).
- Flexible schema for AI metadata (per-camera config, detection payloads,
  product attributes).
- Strict referential integrity for financial data.
- Open licensing, mature tooling, and broad operator familiarity for both
  on-premise and cloud deployments.

## Decision

Use **PostgreSQL 16** as the primary OLTP database. All bounded contexts share
a single Postgres instance, in line with the modular-monolith style (ADR-003).

Specifically we rely on:

- ACID transactions and `SERIALIZABLE` isolation where needed.
- **JSONB** for flexible attribute storage (product attributes, AI configs,
  notification payloads, audit diffs).
- **pgcrypto** for `gen_random_uuid()` (UUID primary keys).
- **pg_trgm** / full-text search for product lookup.
- **Logical replication** for read replicas / analytics.
- Managed equivalents (RDS, Cloud SQL, Azure Database for PostgreSQL) for
  cloud deployments.

## Consequences

**Positive**

- One database engine to operate, monitor, back up, and tune.
- JSONB removes the need for a separate document store.
- Strong consistency simplifies the sales/inventory invariants.
- Excellent tooling: `psql`, `pgAdmin`, `pgBouncer`, `pgBadger`, `pg_dump`.

**Negative**

- Vertical scaling has a ceiling. Cross-region active/active writes are not
  native (we will use active/passive — see ADR-015).
- Operators must know how to vacuum, monitor bloat, and tune autovacuum.

**Neutral**

- The team must agree on a Postgres extension policy: we whitelist only
  extensions available on managed providers.

## Alternatives Considered

- **MySQL / MariaDB** — Capable, but weaker JSON support and weaker
  constraint expressiveness (CHECK, EXCLUDE). Rejected.
- **MongoDB or another document DB** — Inadequate guarantees for financial
  data; would force us to bolt on a SQL store anyway. Rejected as primary.
- **CockroachDB / YugabyteDB** — Tempting for multi-region writes, but
  operationally heavier and less familiar. Reconsider only when multi-region
  write is a hard requirement.
- **SQLite** — Used only for unit tests where convenient; not a production
  option.
