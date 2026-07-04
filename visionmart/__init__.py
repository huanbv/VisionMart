"""VisionMart deployment validation & production readiness — shared engine.

This package answers two related but distinct questions using the SAME
underlying check functions (per the "avoid duplicate functionality"
requirement):

  1. "Is this deployment ready for production?" -- `visionmart.readiness`,
     consumed by the monitoring service's `GET /api/readiness` (proxied by
     the backend at `/ops-monitoring/readiness`, shown on the System
     Health dashboard as the Production Readiness Report).
  2. "Is this specific machine/deployment correctly configured right
     now?" -- `visionmart.doctor`, the `python -m visionmart doctor` CLI,
     meant to be run by a human (or a deploy script) before/after standing
     up the stack on a VPS.

Design notes (why this package exists as its own top-level package rather
than living inside `monitoring/` or `backend/`):

  - It must never import `backend.app.*` or `ai_engine.app.*` (the
    project's app-package-collision rule -- see `monitoring/__init__.py`
    and `backup/__init__.py` for the same reasoning applied elsewhere).
  - It DOES import `monitoring.collectors.*` -- `monitoring` is a sibling
    standalone package (not `backend`'s or `ai_engine`'s `app` package),
    so this is safe, and it is exactly the "reuse existing components"
    the spec asks for: PostgreSQL/Redis/Celery/Docker/host-resource/
    camera/evaluation checking logic already exists in
    `monitoring/collectors/`; this package adds NEW checks only for what
    doesn't already exist (environment/configuration, storage
    permissions, backup directory, log directories, monitoring/evaluation
    service reachability, Python dependency presence) and then merges
    both sets into one report.
  - Every check is read-only. Nothing in this package writes to
    production data, mutates configuration, or restarts anything -- see
    docs/45_DEPLOYMENT_VALIDATION.md for the explicit safety audit.

Because it reuses `monitoring.collectors.*` (which in turn needs
`sqlalchemy`, `asyncpg`, `redis`, `celery`, `docker`, `psutil`), this
package is designed to run inside the **monitoring** container, where all
of those are already installed (see `monitoring/Dockerfile`, which COPYs
this package in alongside `monitoring/`):

    docker compose exec monitoring python -m visionmart doctor

It can also run from a plain host Python with `pip install -r
monitoring/requirements.txt` first, since it has no separate
requirements.txt of its own (intentionally -- importing monitoring's
collectors rather than re-implementing them means there is nothing new to
pin here).
"""

from __future__ import annotations
