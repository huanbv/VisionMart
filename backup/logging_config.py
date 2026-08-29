"""Log rotation for the backup service — same pattern as
`monitoring/logging_config.py` and `evaluation/logging_config.py`
(kept as three small, independent copies rather than a shared import so
each service's Docker image stays self-contained).

Rotated files are gzip-compressed automatically (via the standard
library's `RotatingFileHandler.rotator`/`.namer` hooks) so historical
backup-run logs don't consume disk space unbounded — see
docs/18_LOGGING.md for the project-wide recommended defaults
(30 days / 100MB per file / gzip).
"""

from __future__ import annotations

import gzip
import logging
import logging.handlers
import os
from pathlib import Path

from backup.config import BackupConfig


def _gzip_namer(name: str) -> str:
    return name + ".gz"


def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as sf, gzip.open(dest, "wb") as df:
        df.writelines(sf)
    os.remove(source)


def configure_logging(cfg: BackupConfig) -> None:
    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(cfg.log_dir) / "backup.log"

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

    root = logging.getLogger("backup")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.propagate = False
