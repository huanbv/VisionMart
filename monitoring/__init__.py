"""VisionMart Operational Monitoring layer.

Standalone, read-only, deliberately decoupled from `backend/` and
`ai-engine/`: this package NEVER imports `app.*` from either service. It
observes them exclusively through interfaces that already exist and are
already safe to call from the outside:

  - HTTP: `GET /health` and `GET /metrics` (Prometheus) on both services —
    both endpoints already existed before this package was added (see
    `backend/app/api/metrics.py`, `ai-engine/app/main.py`); nothing was
    changed in either service to support monitoring.
  - Raw, read-only SQL (via `sqlalchemy.text()`, never the ORM models) to
    the backend's Postgres database, using explicit `SELECT` statements.
  - A direct Redis client (`redis-py`) using the same `REDIS_URL` config
    value the rest of the stack already uses.
  - A throwaway Celery control client (`Celery(broker=..., backend=...)`,
    no task modules imported) to ping workers over the existing broker.
  - The Docker Engine API (via the `docker` SDK / `/var/run/docker.sock`)
    for container status, and `psutil`/`pynvml` for host CPU/RAM/GPU/disk.

This design sidesteps a real hazard discovered while building the
`evaluation/` package: `backend` and `ai-engine` each define their own,
unrelated top-level `app` package, so importing both into one Python
process is unsafe. Because `monitoring/` never imports either `app`
package at all, it has no such restriction — every collector here can run
in the same process safely.

Nothing in this package writes to the production Postgres database, the
Shopping Cart, Checkout, Payment, Event Bus, or AI pipeline. It maintains
its own, completely separate SQLite store (see `monitoring/storage/db.py`)
for history, alerts, and the derived session-lifecycle audit trail.
"""

from __future__ import annotations
