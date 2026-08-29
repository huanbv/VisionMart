"""Retention cleanup for completed backups.

Deletes `visionmart-backup-*.zip` (+ matching `.sha256`) older than the
configured retention window. Age is computed from the timestamp encoded
in the filename (falls back to file mtime if the name doesn't parse),
so cleanup is correct even if backups were copied/rsynced elsewhere with
a different mtime.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("backup.retention")

_NAME_RE = re.compile(r"visionmart-backup-(\d{4}-\d{2}-\d{2}-\d{6})\.zip$")


@dataclass
class RetentionResult:
    kept: list[str]
    deleted: list[str]
    errors: list[str]


def _backup_age(zip_path: Path) -> datetime:
    m = _NAME_RE.search(zip_path.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d-%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(zip_path.stat().st_mtime, tz=timezone.utc)


def cleanup_old_backups(output_dir: str, retention_days: int) -> RetentionResult:
    root = Path(output_dir)
    if not root.exists():
        return RetentionResult(kept=[], deleted=[], errors=[f"Backup directory does not exist: {root}"])

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    kept: list[str] = []
    deleted: list[str] = []
    errors: list[str] = []

    for zip_path in sorted(root.glob("visionmart-backup-*.zip")):
        age = _backup_age(zip_path)
        if age >= cutoff:
            kept.append(zip_path.name)
            continue
        try:
            zip_path.unlink()
            checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
            if checksum_path.exists():
                checksum_path.unlink()
            deleted.append(zip_path.name)
            logger.info("Deleted expired backup %s (age cutoff: %s days)", zip_path.name, retention_days)
        except OSError as exc:
            errors.append(f"{zip_path.name}: {exc}")

    return RetentionResult(kept=kept, deleted=deleted, errors=errors)
