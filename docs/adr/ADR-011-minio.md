# ADR-011 — MinIO as the S3-compatible object store

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

The platform produces and consumes large binary artefacts that do not belong
in Postgres:

- Camera snapshots, frames, and short clips for incident review.
- Product images (catalog) and product gallery media.
- Report exports (PDF, XLSX).
- Face embeddings and model artefacts.
- Uploaded CSV / XLSX during bulk imports.

The store must:

- Support the **S3 API** so cloud deployments can use AWS S3, GCS (via
  interop), or Azure Blob (via gateway) without code changes.
- Run **on a customer's VM** for fully on-premise deployments.
- Provide **per-bucket access policies** and **signed URLs** so the browser
  can read/upload directly without proxying every byte through the backend.

## Decision

Use **MinIO** (S3-compatible) as the object store. In cloud deployments
(ADR-015) MinIO is replaced by the cloud-native equivalent through the same
S3 client.

- Backend and AI Engine talk to MinIO with the S3 SDK; the bucket / endpoint
  / credentials come from environment variables.
- Default buckets created on first boot via `scripts/`:
  - `visionmart-product-images`
  - `visionmart-camera-snapshots`
  - `visionmart-clips`
  - `visionmart-reports`
  - `visionmart-embeddings`
  - `visionmart-uploads`
- **Signed read/write URLs** are issued by the backend; the frontend uses them
  directly to avoid proxying media.
- **Bucket policies are least-privilege** and reviewed in code (no public
  buckets by default).
- **Lifecycle rules** auto-delete clips / uploads past their retention TTL.
- Server-side **encryption-at-rest** enabled in production.

## Consequences

**Positive**

- One API across on-premise and every major cloud — no abstraction layer
  needed in application code.
- Decouples large binary data from the OLTP database.
- Mature, well-tested, single-binary deployment for on-premise.

**Negative**

- Self-hosted MinIO is yet another service to monitor and back up.
- MinIO's commercial licensing has tightened in recent years — we pin to a
  version compatible with our needs and re-evaluate on each major release.

**Neutral**

- In multi-node deployments we use distributed MinIO or a managed cloud
  store; the choice is per-environment.

## Alternatives Considered

- **Store binaries in Postgres (`bytea`)** — Bloats the database and ruins
  backup times. Rejected.
- **A local filesystem mount** — Doesn't scale across multiple backend
  pods. Rejected.
- **Direct AWS S3 with no on-premise option** — Conflicts with on-premise
  customer deployments. Rejected.
- **Ceph / SeaweedFS** — Powerful but operationally heavier. Reconsider only
  at very large scale.
