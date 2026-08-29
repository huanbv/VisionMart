"""VisionMart — standalone Automatic Backup service.

Same architectural rule as `monitoring/` and `evaluation/`: this package
never imports `backend.app.*` or `ai_engine.app.*` (those two define
unrelated top-level `app` packages — importing both in one process is
unsafe, a lesson learned while building `evaluation/`). Everything here
talks to the rest of the stack only through interfaces that are already
external and stable:

  - PostgreSQL: the `pg_dump` client binary against `DATABASE_URL`
    (a logical, non-blocking dump — never touches replication slots,
    never takes an exclusive lock, never stops writes).
  - Monitoring's own SQLite file: read via SQLite's built-in online
    backup API (`sqlite3.Connection.backup()`), which is safe to run
    while the monitoring service keeps writing to it (WAL mode).
  - Evaluation reports: a plain filesystem copy of the reports
    directory `evaluate`/`cart-metrics` already write to.
  - Uploaded images/videos: downloaded from the same MinIO bucket the
    backend/ai-engine already use, via the `minio` SDK and the existing
    `MINIO_*` environment variables — no import of backend/ai-engine
    storage helpers needed since the wire protocol is just S3.
  - Configuration files: a plain filesystem copy of an explicit,
    configurable list of paths (docker-compose.yml, nginx conf, docs,
    alembic.ini, etc.). `.env` is excluded unless explicitly enabled,
    since it holds production secrets.

This package only ever *reads* from production sources and *writes*
to its own backup output directory — it never issues a single
INSERT/UPDATE/DELETE against the application database, never deletes
a MinIO object, and never modifies a config file in place.
"""

from __future__ import annotations

__version__ = "1.0.0"
