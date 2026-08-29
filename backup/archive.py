"""Assemble a staging directory into a checksummed, verified zip archive.

Layout inside the zip (matches the spec's example):

    2026-07-04/
        postgres.sql
        monitoring.db
        evaluation/
        uploads/
        config/
        manifest.json

zipped as: visionmart-backup-2026-07-04-020000.zip
alongside: visionmart-backup-2026-07-04-020000.zip.sha256
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from backup.config import BackupConfig
from backup.sources import (
    SourceResult,
    copy_config_files,
    copy_evaluation_reports,
    copy_monitoring_sqlite,
    download_minio_uploads,
    dump_postgres,
)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _read_app_version(repo_root: str) -> str:
    """Reads the centralized `VERSION` file (see docs/44_VERSIONING.md) so
    every backup manifest records exactly which VisionMart version
    produced it -- useful when restoring an old backup to know whether a
    schema/format migration might be needed. `repo_root` is the same
    read-only repo mount already used for `copy_config_files`/
    `copy_evaluation_reports` (`BACKUP_REPO_ROOT`), so this adds no new
    mount or dependency."""
    path = Path(repo_root) / "VERSION"
    if not path.exists():
        return "unknown"
    try:
        return path.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def build_backup(cfg: BackupConfig) -> dict:
    """Run every source, zip the results, checksum + verify the archive.

    Returns a manifest dict describing what happened. Never raises for a
    single source failing — only raises if the zip itself cannot be
    written (disk full, permission denied), which the caller should
    surface loudly since it means the whole backup did not happen.
    """
    started_at = time.time()
    now = datetime.now(timezone.utc)
    day_label = now.strftime("%Y-%m-%d")
    ts_label = now.strftime("%Y-%m-%d-%H%M%S")

    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="visionmart-backup-") as tmp:
        staging_root = Path(tmp) / day_label
        staging_root.mkdir(parents=True, exist_ok=True)

        results: list[SourceResult] = [
            dump_postgres(cfg, staging_root),
            copy_monitoring_sqlite(cfg, staging_root),
            copy_evaluation_reports(cfg, staging_root),
            download_minio_uploads(cfg, staging_root),
            copy_config_files(cfg, staging_root),
        ]

        manifest = {
            "backup_id": ts_label,
            "created_at": now.isoformat(),
            "version": _read_app_version(cfg.repo_root),
            "sources": [asdict(r) for r in results],
            "config": {
                "include_env_file": cfg.include_env_file,
                "include_uploads": cfg.include_uploads,
                "retention_days": cfg.retention_days,
            },
        }
        (staging_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        zip_name = f"visionmart-backup-{ts_label}.zip"
        zip_path = output_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in staging_root.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(staging_root.parent)
                    zf.write(file_path, arcname=str(arcname))

    checksum = _sha256_file(zip_path)
    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    checksum_path.write_text(f"{checksum}  {zip_name}\n", encoding="utf-8")

    verify_ok, verify_detail = verify_archive(zip_path)

    manifest["zip_path"] = str(zip_path)
    manifest["zip_size_bytes"] = zip_path.stat().st_size
    manifest["sha256"] = checksum
    manifest["verified"] = verify_ok
    manifest["verify_detail"] = verify_detail
    manifest["duration_seconds"] = round(time.time() - started_at, 2)
    manifest["overall_ok"] = verify_ok and all(r["ok"] for r in manifest["sources"] if r["name"] == "postgres")

    return manifest


def verify_archive(zip_path: Path) -> tuple[bool, str]:
    """Zip-integrity check (`testzip`) + checksum re-verification against
    the sidecar `.sha256` file, if present. Read-only — never modifies
    the archive."""
    if not zip_path.exists():
        return False, f"Archive not found: {zip_path}"

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad_file = zf.testzip()
        if bad_file is not None:
            return False, f"Corrupt member in archive: {bad_file}"
    except zipfile.BadZipFile as exc:
        return False, f"Not a valid zip file: {exc}"
    except Exception as exc:  # noqa: BLE001 -- a damaged zip can raise zlib/EOF/struct
        # errors from deep inside testzip()'s decompression, not just
        # BadZipFile; any of them means "this backup is not restorable",
        # which must be reported as FAIL, never as an unhandled crash.
        return False, f"Archive is corrupt (decompression error): {exc}"

    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    if checksum_path.exists():
        expected = checksum_path.read_text(encoding="utf-8").split()[0]
        actual = _sha256_file(zip_path)
        if expected != actual:
            return False, f"Checksum mismatch: expected {expected}, got {actual}"
        return True, "Zip structure OK, checksum matches."

    return True, "Zip structure OK (no .sha256 sidecar file found to cross-check)."
