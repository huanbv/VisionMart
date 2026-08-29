# Architecture Decision Records (ADRs)

> **Project:** VisionMart — Enterprise Smart Retail AI Platform
> **Domain:** https://visionmart.thehuan.com
> **Location:** `docs/adr/`

This folder collects every significant architectural decision made on the
VisionMart project. Each ADR is immutable once accepted — to change a decision,
write a new ADR that **supersedes** the previous one.

## Format

Every ADR follows the same structure:

- **Status** — `Proposed`, `Accepted`, `Deprecated`, or `Superseded by ADR-NNN`
- **Date** — ISO date (`YYYY-MM-DD`)
- **Context** — the problem and the forces at play
- **Decision** — what we decided
- **Consequences** — positive, negative, and neutral
- **Alternatives Considered** — what else we looked at, and why we rejected it

## Index

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-001](ADR-001-clean-architecture.md) | Adopt Clean Architecture | Accepted | 2026-06-30 |
| [ADR-002](ADR-002-domain-driven-design.md) | Adopt Domain Driven Design | Accepted | 2026-06-30 |
| [ADR-003](ADR-003-modular-monolith.md) | Modular Monolith as the deployment style | Accepted | 2026-06-30 |
| [ADR-004](ADR-004-postgresql.md) | PostgreSQL as the primary OLTP store | Accepted | 2026-06-30 |
| [ADR-005](ADR-005-fastapi.md) | FastAPI as the backend HTTP framework | Accepted | 2026-06-30 |
| [ADR-006](ADR-006-react.md) | React + TypeScript + Vite for the frontend | Accepted | 2026-06-30 |
| [ADR-007](ADR-007-docker.md) | Docker + Docker Compose as the packaging baseline | Accepted | 2026-06-30 |
| [ADR-008](ADR-008-yolov8.md) | YOLOv8 as the default object detector | Accepted | 2026-06-30 |
| [ADR-009](ADR-009-bytetrack.md) | ByteTrack as the multi-object tracker | Accepted | 2026-06-30 |
| [ADR-010](ADR-010-redis.md) | Redis for cache, queues, and rate limiting | Accepted | 2026-06-30 |
| [ADR-011](ADR-011-minio.md) | MinIO as the S3-compatible object store | Accepted | 2026-06-30 |
| [ADR-012](ADR-012-rest-api.md) | REST + JSON as the primary public API style | Accepted | 2026-06-30 |
| [ADR-013](ADR-013-websocket.md) | WebSocket for real-time browser push | Accepted | 2026-06-30 |
| [ADR-014](ADR-014-future-event-bus.md) | Pluggable EventBus, in-memory now, broker later | Accepted | 2026-06-30 |
| [ADR-015](ADR-015-cloud-deployment.md) | Cloud deployment on Kubernetes (with single-node fallback) | Accepted | 2026-06-30 |
