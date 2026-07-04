"""Log rotation for the Experimental Evaluation Framework's CLI.

Same pattern as `monitoring/logging_config.py` and
`backup/logging_config.py` (kept as independent copies rather than a
shared import — `evaluation/` must stay importable standalone in an
environment that only has the eval framework's own dependencies, per
the app-package-collision design note in `evaluation/README` /
`docs/EVALUATION_FRAMEWORK.md`).

This is purely additive: `evaluation/cli.py`'s existing `_log()` helper
still prints to the console exactly as before; this module only adds a
second, rotating, gzip-compressed file sink under
`<output-dir>/logs/evaluation.log` so a long run (or repeated CI/thesis
runs) doesn't leave unbounded plain-text logs on disk. It does not
change any metrics, dataset, or reporting logic.
"""

from __future__ import annotations

import gzip
import logging
import logging.handlers
import os
from pathlib import Path

_DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB — see docs/18_LOGGING.md
_DEFAULT_BACKUP_COUNT = 5


def _gzip_namer(name: str) -> str:
    return name + ".gz"


def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as sf, gzip.open(dest, "wb") as df:
        df.writelines(sf)
    os.remove(source)


def configure_logging(output_dir: str) -> logging.Logger:
    log_dir = Path(output_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "evaluation.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=_DEFAULT_MAX_BYTES, backupCount=_DEFAULT_BACKUP_COUNT, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.namer = _gzip_namer
    file_handler.rotator = _gzip_rotator

    logger = logging.getLogger("evaluation")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger
