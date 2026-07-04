"""Log rotation configuration for the monitoring service.

Size-based rotation (`RotatingFileHandler`) is used rather than
time-based, so a burst of alert activity can't grow the log file
unboundedly between rotations regardless of wall-clock time.
`log_max_bytes` / `log_backup_count` are both configurable via
`MONITORING_LOG_MAX_BYTES` / `MONITORING_LOG_BACKUP_COUNT` (see
`monitoring/config.py`). Once `backup_count` rotated files exist, the
oldest is deleted automatically by the standard library handler — no
extra cleanup code needed for the log files themselves. Longer-horizon
retention (how many days of snapshots/alerts/session events to keep in
`monitoring.db`) is handled separately by `monitoring/storage/retention.py`,
since that data lives in SQLite rows, not files.

Rotated files are gzip-compressed automatically (`RotatingFileHandler`'s
`namer`/`rotator` hooks — no subclass needed) so a long-running
deployment's historical logs don't consume disk space unbounded. See
docs/18_LOGGING.md for the project-wide recommended defaults (30 days /
100MB per file / gzip) — `evaluation/logging_config.py` and
`backup/logging_config.py` use the identical pattern.
"""

from __future__ import annotations

import gzip
import logging
import logging.handlers
import os
from pathlib import Path

from monitoring.config import MonitoringConfig


def _gzip_namer(name: str) -> str:
    return name + ".gz"


def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as sf, gzip.open(dest, "wb") as df:
        df.writelines(sf)
    os.remove(source)


def configure_logging(cfg: MonitoringConfig) -> None:
    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(cfg.log_dir) / "monitoring.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=cfg.log_max_bytes, backupCount=cfg.log_backup_count, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.namer = _gzip_namer
    file_handler.rotator = _gzip_rotator

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger("monitoring")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.propagate = False
