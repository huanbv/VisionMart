# VisionMart v1.0.0-rc1 — Release Notes

**Release date:** 2026-07-04
**Version:** `1.0.0-rc1` (see `VERSION` at repo root — the single source
of truth for this string; do not hand-edit it in any other file)
**Recommended Git tag:** `v1.0.0-rc1`

---

## Overview

VisionMart is an AI-powered smart retail analytics platform: anonymous,
non-biometric computer-vision customer behavior tracking, AI-assisted
checkout with mandatory human payment confirmation, an experimental
evaluation framework for measuring the vision pipeline, and a full
operational-readiness layer for running the whole stack on a single VPS.

This is the **first release candidate** — feature-complete, with a
dedicated Production Readiness Report and `visionmart doctor` command to
validate a deployment before it goes live.

## Major Features

- **Computer Vision** — YOLOv8 + ByteTrack detection/tracking, optional
  OpenCV preprocessing (ROI, CLAHE, histogram equalization, brightness
  adjustment), cross-camera visitor linking, product-return detection.
  No facial recognition or biometric identification anywhere in the core
  feature set — this is an explicit, permanent design constraint, not a
  temporary limitation.
- **Shopping Cart & Checkout** — AI-inferred cart with per-line and
  cart-level confidence scores; two-step checkout (`request_checkout` →
  human-confirmed `confirm_checkout`); QR/token-based self-checkout with
  a staff-assisted fallback. The AI never confirms or charges a payment.
- **Evaluation Framework** — standalone, read-only benchmarking suite
  producing CSV/XLSX/JSON/Markdown exports and a thesis-style narrative
  report, suitable for an academic evaluation chapter.
- **Operational Monitoring** — read-only observability service covering
  camera, AI pipeline, host/Docker/Celery/Redis/PostgreSQL health, a
  configurable Alert Engine, and a Global System Health Score (0-100 +
  status label) shown prominently on the System Health dashboard.
- **Backup & Recovery** — automated, checksummed, verified backups of
  PostgreSQL, monitoring data, evaluation reports, and MinIO uploads,
  with configurable retention and a documented restore procedure.
- **Deployment Validation** — a Production Readiness Report (API) and a
  `visionmart doctor` CLI, both backed by one shared check engine
  covering 13+ categories (Database, Redis, Celery, Docker, Monitoring,
  Evaluation, Camera, Storage, Backup, Logging, Health, Configuration,
  Security), each returning PASS/WARNING/FAIL with a concrete fix.
- **Centralized Versioning** (this release) — a single `VERSION` file
  drives the version string shown consistently across the release-info
  endpoint, System Health page, monitoring service, evaluation reports,
  and backup metadata.

## Architecture Overview

```
┌─────────────┐   ┌─────────────┐   ┌──────────┐
│   frontend   │──▶│   backend   │──▶│ postgres │
│  (React/TS)  │   │  (FastAPI)  │   │  redis   │
└─────────────┘   └──────┬──────┘   │  minio   │
                          │          └──────────┘
                          ▼
                   ┌─────────────┐
                   │  ai-engine  │  YOLOv8 + ByteTrack + OpenCV vision/
                   │  (FastAPI)  │
                   └─────────────┘

Independent, read-only operational services (none import backend/ai-engine's
`app` package — each talks only over HTTP/SQL/Redis/Celery-broker/Docker API):

  monitoring/   → health/alerts/session audit, Health Score, Release Info, Readiness Report
  backup/       → scheduled, checksummed backups (Postgres/SQLite/MinIO/evaluation/config)
  evaluation/   → offline benchmarking of the OpenCV/YOLO/ByteTrack pipeline
  visionmart/   → shared check engine behind the Readiness Report and `doctor` CLI
```

Every operational package above is additive and was built without
modifying Cart, Checkout, Payment, Computer Vision, the internal Event
Bus, or the database schema.

## Known Limitations

- **No facial recognition / biometric identification** — by design, not
  a gap. Cross-camera linking is anonymous track association, not
  identity resolution.
- **Camera FPS/latency/frozen-frame metrics** depend on
  `ENABLE_PERFORMANCE_METRICS` on ai-engine (default `false`); when off,
  these fields report `null` with a reason rather than a fabricated value.
- **Camera uptime % is not retroactively reconstructable** — the
  `cameras` table only stores current state, so reconnect counts are
  observed going-forward from whenever monitoring/evaluation started.
- **YOLO and ByteTrack timing cannot be separated** in production (both
  run inside a single `model.track()` call).
- **Backup verification checks archive integrity, not restore fidelity**
  — `visionmart-backup-*.zip` is checksum- and zip-structure-verified on
  every run, but there is no automated test-restore into a scratch
  database yet.
- **No dedicated Production Readiness Report dashboard page** — it's
  available via API (`GET /api/v1/ops-monitoring/readiness`) and the
  `visionmart doctor` CLI, matching the spec's "expose via API" wording;
  the Health Score (which the spec did ask to be "displayed prominently")
  already has full dashboard treatment.
- **No log-aggregation platform** (ELK/Loki) — log rotation/retention is
  handled per-service (Docker `local` driver + gzip `RotatingFileHandler`),
  sufficient for a single-VPS deployment but not centralized search.
- This is a **release candidate**, not a final GA release — see the
  Release Checklist in the accompanying delivery summary before
  promoting to `v1.0.0`.

## Deployment Requirements

- Docker Engine ≥ 20.10 (required for the `local` logging driver used for
  log rotation/compression).
- Single VPS is sufficient for the current architecture (CPU-only YOLO
  inference supported; GPU optional, auto-detected, never required).
- PostgreSQL, Redis, MinIO — provisioned via the existing
  `docker-compose.yml` (no external managed services required).
- Before first boot: copy `.env.example` → `.env`, replace every
  `change-me-*` placeholder secret (`BACKEND_SECRET_KEY`,
  `MONITORING_API_TOKEN`, `MINIO_ROOT_PASSWORD`) with strong generated
  values — `visionmart doctor`'s Security category will `FAIL`/`WARN` on
  any left at their `.env.example` default.
- Run `python3 scripts/generate_release_info.py` once per build/deploy so
  the Release Information panel shows real git/build data instead of
  "unknown".
- Recommended pre-go-live check:
  `docker compose exec monitoring python -m visionmart doctor` — should
  exit `0` (no critical `FAIL`) before serving production traffic.

## Upgrade Notes

This is the first tagged release — there is no prior version to upgrade
from within this project's own versioning scheme. If you were running an
untagged pre-release checkout of this repository:

- Run `python3 scripts/generate_release_info.py` after pulling, so the
  Release Information panel picks up the new centralized `VERSION` file.
- No database migrations are introduced by this release (no schema
  changes were made as part of version-centralization work).
- If you were already using the older `scripts/backup.sh`/
  `scripts/restore.sh` pair, note that the new `backup/` package uses a
  **different, incompatible archive format** — see
  [docs/43_BACKUP_RECOVERY.md](docs/43_BACKUP_RECOVERY.md) before mixing
  the two.
- No breaking API changes. The only API-visible change in this release
  is that backend's existing `/health` and `/ready` `version` field (and
  ai-engine's equivalent) now report `1.0.0-rc1` instead of `0.1.0` — the
  field already existed, only the value changed.

---

*For the itemized list of files added/modified and the full release
checklist, see the delivery summary accompanying this release in the
project conversation, or `CHANGELOG.md` for a categorized history.*
