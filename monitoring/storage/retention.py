"""Retention sweep for monitoring's own SQLite store.

Deletes rows older than `MONITORING_RETENTION_DAYS` (default 30) from
`resource_snapshots`, `camera_state_events`, `session_lifecycle_events`,
and resolved (not active) rows from `alerts`. Runs on a periodic timer
from `monitoring/scheduler.py` — see that module for the schedule. This
only ever touches `monitoring.db` (monitoring's own file); it has no
access path to production Postgres at all (no `DATABASE_URL` is passed
in here).
"""

from __future__ import annotations

import logging

from monitoring.storage import db as monitoring_db

logger = logging.getLogger("monitoring.retention")


def run_retention_sweep(sqlite_path: str, retention_days: int) -> dict:
    deleted = monitoring_db.purge_older_than(sqlite_path, retention_days)
    total = sum(deleted.values())
    if total:
        logger.info("Retention sweep removed %d rows older than %d days: %s", total, retention_days, deleted)
    else:
        logger.info("Retention sweep: nothing older than %d days to remove.", retention_days)
    return deleted
