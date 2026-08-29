# ADR-015 — Cloud deployment on Kubernetes (with single-node fallback)

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart serves two markets with very different operational realities:

1. **Single-store / pilot customers** — One physical store, modest budget,
   no dedicated SRE. Wants something that runs on a VM and is upgraded by an
   IT generalist.
2. **Chains and enterprise customers** — Many stores, regulated environments,
   need HA, autoscaling, multi-region, and a real backup story.

We cannot pick *only* Docker Compose (won't satisfy market #2) or *only*
Kubernetes (overkill for market #1). The two deployment targets must share
the same images, the same configuration model, and the same domain code.

## Decision

Adopt a **two-tier deployment story** built on the same artefacts (ADR-007):

- **Tier 1 — Single-node Docker Compose** for pilots and small customers.
  Documented in `docs/07_DEPLOYMENT_PLAN.md`. The full stack runs behind one
  Nginx on one VM, with nightly backups to off-site storage.
- **Tier 2 — Kubernetes** as the production target for chains and SaaS
  deployments. Documented in `docs/42_CLOUD_SCALING.md`.

For Tier 2:

- **Helm chart** (or Kustomize overlay) ships from this repository.
- **Stateless backend** instances are horizontally scalable behind a service
  + ingress; state lives in Postgres (ADR-004), Redis (ADR-010), and MinIO /
  cloud object storage (ADR-011).
- **AI workers** scale on queue depth (KEDA or equivalent) and may run on
  GPU node pools.
- **Cloud-managed services** are preferred where available:
  - Postgres → RDS / Cloud SQL / Azure Database for PostgreSQL.
  - Redis → ElastiCache / Memorystore / Azure Cache.
  - Object storage → S3 / GCS / Azure Blob (S3 API).
  - Secrets → AWS Secrets Manager / GCP Secret Manager / Azure Key Vault,
    surfaced into pods via External Secrets or Sealed Secrets.
- **Observability** is Prometheus + Grafana + Loki + Tempo (or vendor
  equivalents); every service exposes metrics, structured logs, and trace
  spans correlated by `X-Request-ID`.
- **TLS** is managed by cert-manager.
- **Backups**: Postgres PITR + nightly snapshots; MinIO / S3 versioning +
  lifecycle rules. A documented restore drill runs at least quarterly.
- **Multi-region** topology is supported as **active management plane + edge
  AI nodes** for v1.3, and **active/active reads + active/passive writes** at
  v2.0. Multi-master writes are explicitly out of scope until a customer
  requires them.

## Consequences

**Positive**

- One codebase, two deployment shapes, no fork.
- Customers can start on Compose and graduate to Kubernetes without
  re-platforming.
- Cloud-managed services remove a class of operational burden in Tier 2.

**Negative**

- Two deployment targets mean two sets of deployment docs and two upgrade
  procedures.
- The team must be comfortable with both `docker compose` and Kubernetes
  primitives.

**Neutral**

- We deliberately do not lock in to a single cloud — the Helm chart values
  are written to be cloud-agnostic. Vendor-specific Terraform modules ship as
  reference, not requirements.

## Alternatives Considered

- **SaaS-only (managed by us, never installed on-prem)** — Loses a large
  segment of the target market. Rejected for the foreseeable future.
- **On-prem only** — Forecloses the SaaS opportunity. Rejected.
- **Bare-metal cluster (no Kubernetes)** — Possible but multiplies the
  operational surface; rejected outside niche edge cases.
- **Nomad / ECS / Cloud Run** — Each viable; Kubernetes wins on portability
  across customers' chosen clouds.
- **Serverless functions for the API** — Cold starts and WebSocket support
  are awkward; rejected for the core API.
