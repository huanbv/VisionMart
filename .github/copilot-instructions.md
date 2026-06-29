# VisionMart — Project Constitution

> This document is the **single source of truth** for how the VisionMart codebase
> is designed, built, and evolved. Every contributor — human or AI — must read it
> before making changes. When this document and any other guideline conflict,
> **this document wins**.

---

## 1. Project Identity

- **Project Name:** VisionMart
- **Domain:** [visionmart.thehuan.com](https://visionmart.thehuan.com)
- **Repository:** https://github.com/huanbv/VisionMart
- **Purpose:** An enterprise-grade **Smart Retail AI platform** powered by
  Computer Vision. VisionMart turns ordinary store cameras into an intelligent
  retail operations layer — customer recognition, automated checkout, shelf and
  inventory analytics, employee activity monitoring, and real-time business
  insights — all delivered through a unified web platform.
- **Long-term Vision:** Become the reference open architecture for AI-driven
  brick-and-mortar retail: multi-tenant, multi-branch, modular, observable,
  and deployable from a single laptop to a multi-region cluster without
  rewriting code. The system must remain useful 5+ years from now by keeping
  business rules, AI inference, and infrastructure cleanly separated.

---

## 2. Development Principles

These principles are **non-negotiable**. Any pull request that violates one
must justify the exception in its description.

- **Clean Architecture** — Dependencies point inward: `api → application →
  domain ← infrastructure`. The domain layer never imports frameworks.
- **Domain Driven Design (DDD)** — The codebase is organised by **bounded
  contexts** (`tenancy`, `identity`, `catalog`, `sales`, `inventory`,
  `camera`, `notification`, `audit`, …). Aggregates own their invariants.
- **SOLID** — Single Responsibility, Open/Closed, Liskov, Interface Segregation,
  Dependency Inversion. Concrete implementations depend on abstractions, not
  the other way around.
- **DRY** — No copy-paste. Shared behaviour lives in `app/core`, `app/database`,
  or `app/repositories`.
- **KISS** — Choose the simplest design that satisfies the requirement. Add
  complexity only when a real, demonstrated need arises.
- **Modular Monolith** — One deployable, many independent modules. Modules
  communicate via the shared `EventBus` interface and explicit application
  services — **never** via cross-module ORM relationships.
- **Event-Driven Ready** — Domain events are first-class citizens. The current
  `InMemoryEventBus` must be swappable for a real broker (Redis Streams,
  RabbitMQ, Kafka) without touching domain code.
- **API First** — Every feature begins with a versioned REST contract under
  `/api/v1/...`. OpenAPI is the source of truth for the frontend.
- **Testable Code** — If a piece of logic cannot be tested without a running
  database or external service, it lives in the wrong layer.
- **Maintainability over Cleverness** — Write code for the next engineer.
  Boring, explicit code is preferred over elegant tricks.

---

## 3. Technology Stack

The stack below is **fixed**. Adding or replacing a major component requires
an architecture decision record and explicit approval.

### Backend
- **Python 3.12**
- **FastAPI** — HTTP and WebSocket framework
- **SQLAlchemy 2.x** — async ORM, typed `Mapped[T]` style
- **Alembic** — schema migrations
- **PostgreSQL 16** — primary OLTP store
- **Redis 7** — cache, rate limiting, Celery broker / result backend
- **Celery 5** — background and scheduled jobs

### Frontend
- **React 18**
- **TypeScript 5**
- **Vite 5**
- **TailwindCSS 3**
- **Ant Design 5**

### AI Engine
- **Python 3.12**
- **OpenCV** — frame capture and preprocessing
- **YOLOv8** — object / person / product detection
- **ByteTrack** — multi-object tracking across frames
- **ONNX Runtime** — production inference backend (CPU / CUDA / TensorRT)

### Infrastructure
- **Docker** + **Docker Compose v2** — local and single-host deployments
- **Nginx 1.27-alpine** — reverse proxy, TLS termination, rate limiting
- **MinIO** — S3-compatible object storage (frames, snapshots, embeddings)

---

## 4. Coding Rules

- **English only** for all identifiers, file names, log messages, and code
  comments. User-facing strings may be localised through the i18n layer.
- **Type hints everywhere.** Python: full annotations including return types.
  TypeScript: `strict: true`, no implicit `any`.
- **Small functions.** Target ≤ 40 lines. If a function grows beyond that,
  extract collaborators.
- **One responsibility per class.** A class either *represents* something or
  *does* something — never both.
- **No duplicated logic.** Extract to a helper, a mixin, a base class, or a
  service the second time you write the same thing.
- **Composition over inheritance.** Use inheritance only for true *is-a*
  relationships; otherwise inject collaborators.
- **Never hardcode configuration values.** No URLs, secrets, ports, file
  paths, feature flags, or tunables embedded in source code.
- **Always read configuration from environment variables**, exposed through
  `app.config.settings.Settings` (pydantic-settings). Frontend reads from
  `import.meta.env.VITE_*`.
- **Tests where practical.** Every new module ships with unit tests for its
  domain and application layers. Infrastructure tests are integration-level.
- **Async all the way down** in the backend — no blocking I/O inside request
  handlers or Celery tasks that interact with the DB.
- **No `print()`** in production code. Use the structured logger.

---

## 5. Repository Rules

- **Never modify unrelated files.** A PR titled "add Foo" does not touch Bar.
- **Always preserve existing architecture.** Do not relocate a module,
  rename a layer, or introduce a new top-level folder without prior discussion.
- **Do not introduce unnecessary dependencies.** New runtime dependencies
  require justification in the PR description. Prefer the standard library
  and existing libraries already in `pyproject` / `package.json`.
- **Keep commits focused.** One logical change per commit. Use
  Conventional Commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`,
  `chore:`, `test:`, `ci:`, `build:`.
- **No force-push** to `main` and no rewriting of published history.
- **Never commit secrets.** `.env` is gitignored; use `.env.example` for
  documentation.
- **No generated artefacts in git** (`__pycache__`, `dist/`, `node_modules/`,
  model weights, frames, logs).

---

## 6. Response Rules

When implementing a new feature, the assistant must follow this exact flow:

1. **Explain the implementation plan briefly** — one short paragraph or a
   handful of bullet points. No essays.
2. **List the files that will be changed** — full workspace-relative paths.
3. **Implement only the requested scope.** Do not refactor neighbouring code,
   do not "while I'm here" fix unrelated issues.
4. **Stop after completion.** Report what was done in a short summary, then
   wait for the next instruction.

**Never implement additional features without explicit instruction.** If a
related improvement is obvious, mention it as a suggestion and wait for
approval.

---

## 7. Quality Standards

- **Enterprise practices first.** Logging, error handling, observability,
  graceful shutdown, healthchecks, migrations, and security headers are
  baseline expectations — not bonus features.
- **Readability over optimisation.** Optimise only when a measurement proves
  a real bottleneck. Document why the optimised version exists.
- **Design for future scalability.** Stateless services, idempotent jobs,
  bounded queues, configurable concurrency. Prefer horizontal scaling.
- **No placeholder business logic.** Stub functions that silently return
  fake data are forbidden. Either implement the real behaviour or raise
  `NotImplementedError` with a clear message and a tracking reference.
- **Security by default.** Validate at system boundaries (HTTP, message
  broker, file upload). Parameterised queries only. Secrets via environment
  or secret manager. CORS and CSP locked down.
- **Observability by default.** Structured JSON logs, request IDs propagated
  end-to-end, Prometheus-compatible metrics exposed where applicable.

---

## 8. Layered Architecture Reference

```
backend/app/
├── api/                  # HTTP routers, request/response shaping only
├── core/                 # Cross-cutting (events, logging, security)
├── config/               # Settings, environment binding
├── database/             # Base, mixins, session, types
├── repositories/         # Generic data-access building blocks
├── dependencies/         # FastAPI DI providers
├── middleware/           # ASGI middleware
├── workers/              # Celery app and tasks
├── models/               # Central ORM registry (imports every module)
└── modules/<context>/
    ├── api/              # Module-scoped routers
    ├── application/      # Use cases / services / commands / queries
    ├── domain/           # Entities, value objects, domain events, rules
    ├── infrastructure/   # ORM models, repository implementations
    └── schemas/          # Pydantic DTOs (request/response)
```

**Allowed import direction inside a module:**
`api → application → domain` and `infrastructure → domain`.
The `domain` layer imports **nothing** from the other layers.

**Allowed cross-module communication:**
- Publish / subscribe to `DomainEvent`s via the shared `EventBus`.
- Call another module's **application service** through a published interface.
- FK columns may reference another module's table, but SQLAlchemy
  `relationship()` may not cross module boundaries.

---

## 9. Definition of Done

A change is "done" only when **all** of the following are true:

- [ ] Code compiles, type-checks, and lints cleanly.
- [ ] Unit tests for new domain / application logic exist and pass.
- [ ] Existing tests still pass.
- [ ] No new hardcoded values; new configuration is in `Settings` and
      documented in `.env.example`.
- [ ] Public API changes are reflected in OpenAPI and, if user-facing, in
      the relevant document under `docs/`.
- [ ] Migrations are generated and reviewed for destructive operations.
- [ ] The commit message follows the Conventional Commits convention.
- [ ] The PR description states *what* changed and *why*.

---

*This constitution evolves. Propose amendments via a dedicated PR that touches
only this file and explains the rationale.*
