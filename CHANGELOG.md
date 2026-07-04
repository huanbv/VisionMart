# Changelog

All notable changes to VisionMart are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses a `MAJOR.MINOR.PATCH[-PRERELEASE]` scheme (see
[docs/44_VERSIONING.md](docs/44_VERSIONING.md) for how the version string
is centralized and where it's displayed). The canonical current version
lives in the `VERSION` file at the repo root.

## [Unreleased]

Nothing yet — `v1.0.0-rc1` is the current release candidate.

## [1.0.0-rc1] - 2026-07-04

First official release candidate. VisionMart is now feature-complete:
anonymous computer-vision-based customer behavior analytics, AI-assisted
checkout with human-confirmed payment, an experimental evaluation
framework, and a full operational-readiness layer (monitoring, backup,
logging, health scoring, deployment validation) for VPS deployment.

### Added — Computer Vision

- YOLOv8 object detection + ByteTrack multi-object tracking pipeline for
  anonymous, non-biometric customer and product tracking across camera
  feeds (`ai-engine/app/services/yolo_detector.py`, `person_tracker.py`).
- Cross-camera global-visitor linking so a shopper's session can be
  followed as they move between camera zones without any facial
  recognition or identity resolution.
- `product_returned` detection logic and continuous frame-capture loop
  for checkout/shelf cameras, feeding the cart-inference pipeline.
- Explicit, enforced constraint throughout: no facial recognition or
  biometric identification anywhere in the core feature set.

### Added — OpenCV Integration (Sprint 1)

- New `ai-engine/app/vision/` package: ROI cropping, CLAHE contrast
  enhancement, histogram equalization, brightness adjustment, and frame
  quality scoring — all optional (`ENABLE_*` flags default to `false`,
  pipeline behavior is byte-for-byte unchanged unless explicitly enabled).
- Per-module cost/benefit instrumentation (latency added vs. detection
  quality impact) usable from both production (behind flags) and the
  Evaluation Framework's standalone module benchmarking.
- Backward-compatibility benchmark suite confirming zero regression when
  all flags are left at their defaults.

### Added — Shopping Cart & Checkout

- AI-inferred cart engine translating detection/tracking events into
  cart line items, with a confidence score per line and for the cart
  total.
- Two-step checkout flow: `request_checkout` (AI-triggered) followed by
  a required **human-confirmed** `confirm_checkout` — the AI never
  confirms or charges a payment on its own, by design and by code path.
- QR-code / token-based payment confirmation directly on the customer's
  own cart (SVG QR generation, no `Pillow` dependency), plus a
  staff-assisted confirmation path for customers without the QR flow.
- Pending-checkout expiry handling, row-level cart locking to prevent
  checkout race conditions, and collision-safe order code generation
  under concurrent checkouts.
- Rate limiting on public, unauthenticated `/shop/*` customer-facing
  endpoints.
- Internal event bus (`app/core/events/`) carrying checkout lifecycle
  events (`checkout_initiated`, `checkout_confirmed`, `checkout_expired`,
  etc.) consumed by monitoring's read-only session-lifecycle audit.

### Added — Evaluation Framework

- Standalone `evaluation/` package (deliberately never imports
  `backend.app.*`/`ai_engine.app.*` in the same process) benchmarking the
  7 OpenCV preprocessing configurations against pipeline latency, camera
  quality, detection, and tracking metrics.
- Read-only Shopping Cart / Order / Camera metrics collector
  (`evaluation/cart/cart_metrics.py`), run as a separate process from the
  vision benchmarks, never touching production data beyond `SELECT`.
- CSV / XLSX / JSON / Markdown exporters plus chart generation and a full
  thesis-style report generator (`evaluation/reporting/thesis_report.py`)
  suitable for an academic defense chapter.
- `python -m evaluation.cli` with `evaluate`, `cart-metrics`, and
  `thesis-report` subcommands.

### Added — Operational Monitoring

- Standalone `monitoring/` service (FastAPI + asyncio poller + its own
  SQLite store) observing camera connectivity, AI pipeline health, host
  resources (CPU/RAM/GPU/disk), Docker/Celery/Redis/PostgreSQL — entirely
  read-only, never imports backend/ai-engine application code.
- Configurable Alert Engine (11 default rules) with active/resolved
  lifecycle tracking and optional Slack/Discord-compatible webhook
  notifications.
- Read-only shopping-session lifecycle audit log.
- **Global System Health Score** (0-100 + Healthy/Warning/Degraded/
  Critical/Offline status), aggregating every collector above into one
  auditable, weighted score with a forced-Offline override when both
  Backend and PostgreSQL are unreachable simultaneously.
- **Release Information** endpoint merging build-time facts (git commit,
  build time, Docker image tag, pinned runtimes) with live runtime facts
  (container Python/OS/kernel, live PostgreSQL version).
- **Production Readiness Report** (`GET /api/readiness`) and the
  **`visionmart doctor`** CLI — one shared check engine (`visionmart/`)
  covering Database, Redis, Celery, Docker, Monitoring, Evaluation,
  Camera, Storage, Backup, Logging, Health, Configuration, and Security,
  each PASS/WARNING/FAIL with a concrete recommendation.
- Authenticated backend proxy (`backend/app/modules/ops_monitoring/`)
  reusing the app's existing staff JWT/role auth — the monitoring
  service's own token never reaches the browser.
- "Giám sát hệ thống" (System Health) frontend page displaying the health
  score prominently, live camera/AI/infrastructure status, active
  alerts, session lifecycle, and release information.

### Added — Backup & Recovery

- Standalone `backup/` package: `pg_dump` (non-blocking) PostgreSQL
  dump, SQLite Online Backup API copy of monitoring data, evaluation
  report archival, MinIO upload download, and config-file snapshotting —
  packaged into a checksummed, verified `visionmart-backup-<ts>.zip`.
- Configurable retention (7/30/90-day presets via `BACKUP_RETENTION_DAYS`),
  automatic cleanup, and a manual `python -m backup.cli {run,list,verify,
  cleanup,schedule}` CLI.
- `docker-compose.yml` `backup` (always-on scheduler) and `backup-once`
  (one-shot, cron-friendly) services, opt-in via Compose profiles.
- Full restore procedure documented in
  [docs/43_BACKUP_RECOVERY.md](docs/43_BACKUP_RECOVERY.md).

### Added — Deployment Validation

- `docker-compose.yml` `local` logging driver (compressed rotation) for
  backend/ai-engine/celery/frontend/nginx/monitoring, plus gzip
  `RotatingFileHandler` rotation for the standalone Python services
  (monitoring, backup, evaluation) — log growth is now bounded on every
  service, by design.
- `visionmart doctor` deployment validation command (see Operational
  Monitoring above) with a non-zero exit code on any critical `FAIL`.
- Explicit production-safety audit confirming every new component in this
  release (backup, health score, release info, readiness report, doctor)
  is read-only with respect to production — documented in
  [docs/46_DEPLOYMENT_VALIDATION.md](docs/46_DEPLOYMENT_VALIDATION.md).
- Centralized `VERSION` file (this release) as the single source of
  truth for the project's version string, surfaced consistently across
  the release-information endpoint, System Health page, monitoring
  service, evaluation reports, and backup metadata.

### Known Limitations

See [RELEASE_NOTES_v1.0.0-rc1.md](RELEASE_NOTES_v1.0.0-rc1.md) for the
full list — highlights: no facial recognition by design (not a gap, a
constraint); camera uptime history and FPS/latency depend on optional
flags (`ENABLE_PERFORMANCE_METRICS`) that default off; backup verification
checks archive integrity but does not perform an automated test-restore;
no dedicated Production Readiness Report dashboard page (API/CLI only).

[Unreleased]: https://github.com/huanbv/VisionMart/compare/v1.0.0-rc1...HEAD
[1.0.0-rc1]: https://github.com/huanbv/VisionMart/releases/tag/v1.0.0-rc1
