# ADR-007 — Docker + Docker Compose as the packaging baseline

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

VisionMart targets two very different deployment scenarios:

1. **Single-node** — a customer VM running the full stack behind one Nginx.
2. **Multi-node cluster** — a managed Kubernetes deployment (ADR-015).

Both scenarios need a reproducible, language-agnostic packaging unit. The
codebase spans Python (backend + AI engine), Node.js (frontend build), and
several supporting services (Postgres, Redis, MinIO, Nginx). The same artefact
must run on a developer laptop, in CI, and in production.

## Decision

Adopt **Docker** as the unit of packaging and **Docker Compose v2** as the
baseline local + single-node orchestration tool.

- Every service ships a **multi-stage Dockerfile** with at least
  `base → deps → dev → runtime` stages.
- Runtime images run as a **non-root user**, declare a healthcheck, and accept
  configuration only via environment variables.
- A single `docker-compose.yml` at the repository root brings up the full
  stack (Postgres, Redis, MinIO, backend, AI engine, Celery worker, frontend,
  Nginx).
- Production images are tagged with the semver tag and the git SHA, and pushed
  to a container registry by CI.
- For Kubernetes (ADR-015) we use the same images; only the orchestration
  layer changes.

## Consequences

**Positive**

- "It works on my machine" failures are reduced to image-tag mismatches,
  which are easy to detect.
- Onboarding is `git clone && docker compose up -d`.
- Identical artefacts run in dev, CI, staging, and production.
- Security patches arrive via base-image upgrades and rebuilds, not via
  per-host package management.

**Negative**

- The container ecosystem has its own learning curve (volumes, networks,
  buildx, layer caching).
- AI Engine GPU support requires NVIDIA Container Toolkit on hosts that
  expose GPUs; this is documented in `docs/41_DEPLOYMENT_GPU.md`.

**Neutral**

- We pin base-image digests in production builds to make supply-chain risk
  visible.

## Alternatives Considered

- **Bare-metal / virtualenv-based deployment** — Faster to start once, slower
  forever after. Rejected.
- **Nix / NixOS for reproducible builds** — Strong guarantees but a niche
  skillset. Rejected.
- **Podman as the runtime** — Drop-in compatible. We standardise on Docker
  for tooling and CI familiarity; Podman remains a fallback.
