"""Individual, independently-failing backup sources.

Every function here is a pure "read from a live source, write into a
staging directory" operation, wrapped so that a failure in one source
(e.g. MinIO unreachable) never prevents the other sources from being
backed up. Each returns a `SourceResult` so the caller can build an
honest manifest — a backup that partially succeeded says so explicitly
instead of silently producing an incomplete archive that looks complete.

Nothing in this module ever mutates the source it reads from:
  - `pg_dump` opens a normal read-only logical dump transaction — it
    does not lock tables against writers/readers and does not stop the
    database (see https://www.postgresql.org/docs/current/app-pgdump.html:
    "pg_dump does not block other users accessing the database").
  - The monitoring SQLite copy uses SQLite's own *online backup API*,
    designed exactly for copying a database that may still be written
    to concurrently.
  - MinIO objects are only ever read (`fget_object`/`list_objects`),
    never deleted or overwritten.
  - Config files are only ever read and copied, never edited.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backup.config import BackupConfig


@dataclass
class SourceResult:
    name: str
    ok: bool
    detail: str
    bytes_written: int = 0


def dump_postgres(cfg: BackupConfig, dest_dir: Path) -> SourceResult:
    """Logical dump via `pg_dump` — non-blocking, does not stop production."""
    dsn = cfg.postgres
    dest_file = dest_dir / "postgres.sql"
    env = dict(os.environ)
    if dsn.password:
        env["PGPASSWORD"] = dsn.password

    cmd = [
        "pg_dump",
        "-h", dsn.host,
        "-p", str(dsn.port),
        "-U", dsn.user,
        "-d", dsn.database,
        "--no-owner",
        "--no-privileges",
        "-f", str(dest_file),
    ]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        return SourceResult("postgres", False, "`pg_dump` binary not found in the backup container's PATH.")
    except subprocess.TimeoutExpired:
        return SourceResult("postgres", False, "pg_dump timed out after 30 minutes.")

    if proc.returncode != 0:
        return SourceResult("postgres", False, f"pg_dump exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    size = dest_file.stat().st_size if dest_file.exists() else 0
    return SourceResult("postgres", True, f"Dumped database '{dsn.database}' from {dsn.host}:{dsn.port}.", size)


def copy_monitoring_sqlite(cfg: BackupConfig, dest_dir: Path) -> SourceResult:
    """Safe *online* copy of the monitoring SQLite file via SQLite's own
    backup API — correct even while the monitoring poller keeps writing
    to it in WAL mode, unlike a plain `shutil.copy`."""
    src_path = Path(cfg.monitoring_sqlite_path)
    dest_path = dest_dir / "monitoring.db"
    if not src_path.exists():
        return SourceResult("monitoring_sqlite", False, f"Not found: {src_path} (monitoring service may not have run yet).")

    try:
        src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
        dest_conn = sqlite3.connect(str(dest_path))
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()
    except Exception as exc:  # noqa: BLE001
        return SourceResult("monitoring_sqlite", False, f"SQLite online backup failed: {exc}")

    size = dest_path.stat().st_size if dest_path.exists() else 0
    return SourceResult("monitoring_sqlite", True, f"Copied {src_path} via SQLite online backup API.", size)


def copy_evaluation_reports(cfg: BackupConfig, dest_dir: Path) -> SourceResult:
    src = Path(cfg.evaluation_reports_dir)
    dest = dest_dir / "evaluation"
    if not src.exists():
        return SourceResult("evaluation_reports", False, f"Not found: {src} (no evaluation run has produced reports yet, or BACKUP_EVALUATION_REPORTS_DIR is misconfigured).")
    try:
        shutil.copytree(src, dest, dirs_exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return SourceResult("evaluation_reports", False, f"Copy failed: {exc}")

    total = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    return SourceResult("evaluation_reports", True, f"Copied evaluation reports from {src}.", total)


def copy_config_files(cfg: BackupConfig, dest_dir: Path) -> SourceResult:
    repo_root = Path(cfg.repo_root)
    dest = dest_dir / "config"
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []

    for rel in cfg.config_file_globs:
        src = repo_root / rel
        if src.name == ".env" and not cfg.include_env_file:
            skipped.append(f"{rel} (excluded — .env holds secrets; set BACKUP_INCLUDE_ENV_FILE=true to include)")
            continue
        if not src.exists():
            skipped.append(f"{rel} (not found)")
            continue
        target = dest / rel
        try:
            if src.is_dir():
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
            copied.append(rel)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{rel} (error: {exc})")

    total = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    detail = f"Copied {len(copied)} path(s): {', '.join(copied) or '-'}."
    if skipped:
        detail += f" Skipped {len(skipped)}: {', '.join(skipped)}."
    return SourceResult("config_files", len(copied) > 0, detail, total)


def download_minio_uploads(cfg: BackupConfig, dest_dir: Path) -> SourceResult:
    if not cfg.include_uploads:
        return SourceResult("uploads", False, "Skipped — BACKUP_INCLUDE_UPLOADS=false.")

    try:
        from minio import Minio
    except ImportError:
        return SourceResult("uploads", False, "`minio` package not installed in the backup service's environment.")

    dest = dest_dir / "uploads"
    dest.mkdir(parents=True, exist_ok=True)

    try:
        client = Minio(
            cfg.minio_endpoint,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            secure=cfg.minio_use_ssl,
        )
        if not client.bucket_exists(cfg.minio_bucket):
            return SourceResult("uploads", False, f"Bucket '{cfg.minio_bucket}' does not exist on {cfg.minio_endpoint}.")

        count = 0
        total_bytes = 0
        for obj in client.list_objects(cfg.minio_bucket, recursive=True):
            local_path = dest / obj.object_name
            local_path.parent.mkdir(parents=True, exist_ok=True)
            client.fget_object(cfg.minio_bucket, obj.object_name, str(local_path))
            count += 1
            total_bytes += local_path.stat().st_size if local_path.exists() else 0
        return SourceResult("uploads", True, f"Downloaded {count} object(s) from bucket '{cfg.minio_bucket}'.", total_bytes)
    except Exception as exc:  # noqa: BLE001
        return SourceResult("uploads", False, f"MinIO download failed: {exc}")
