"""Environment-driven configuration for the backup service.

Every value has a safe default so a backup can run (and honestly report
what it could/couldn't reach) even if some optional source (MinIO,
evaluation reports dir) isn't present in a given deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


def _str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None else v


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: list[str]) -> list[str]:
    v = os.getenv(name)
    if v is None or not v.strip():
        return default
    return [p.strip() for p in v.split(",") if p.strip()]


@dataclass(frozen=True)
class PostgresDsn:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def parse(cls, database_url: str) -> "PostgresDsn":
        # database_url is SQLAlchemy-style, e.g.
        # postgresql+asyncpg://visionmart:visionmart@postgres:5432/visionmart
        parsed = urlparse(database_url.replace("+asyncpg", "").replace("+psycopg2", ""))
        return cls(
            host=parsed.hostname or "postgres",
            port=parsed.port or 5432,
            user=parsed.username or "visionmart",
            password=parsed.password or "",
            database=(parsed.path or "/visionmart").lstrip("/") or "visionmart",
        )


@dataclass(frozen=True)
class BackupConfig:
    # --- Sources (read-only) ---
    database_url: str = field(default_factory=lambda: _str("DATABASE_URL", "postgresql+asyncpg://visionmart:visionmart@postgres:5432/visionmart"))
    monitoring_sqlite_path: str = field(default_factory=lambda: _str("MONITORING_SQLITE_PATH", "/data/monitoring.db"))
    evaluation_reports_dir: str = field(default_factory=lambda: _str("BACKUP_EVALUATION_REPORTS_DIR", "/app/repo/evaluation_results"))

    # --- MinIO (uploaded images/videos) ---
    include_uploads: bool = field(default_factory=lambda: _bool("BACKUP_INCLUDE_UPLOADS", True))
    minio_endpoint: str = field(default_factory=lambda: _str("MINIO_ENDPOINT", "minio:9000"))
    minio_access_key: str = field(default_factory=lambda: _str("MINIO_ROOT_USER", "visionmart"))
    minio_secret_key: str = field(default_factory=lambda: _str("MINIO_ROOT_PASSWORD", "visionmart-minio"))
    minio_bucket: str = field(default_factory=lambda: _str("MINIO_BUCKET", "visionmart"))
    minio_use_ssl: bool = field(default_factory=lambda: _bool("MINIO_USE_SSL", False))

    # --- Config files (repo root mounted read-only into the backup container) ---
    repo_root: str = field(default_factory=lambda: _str("BACKUP_REPO_ROOT", "/app/repo"))
    config_file_globs: list[str] = field(default_factory=lambda: _list(
        "BACKUP_CONFIG_FILES",
        [
            "docker-compose.yml",
            "docker-compose.prod.yml",
            ".env.example",
            "alembic.ini",
            "backend/alembic.ini",
            "docker/nginx/nginx.conf",
            "docker/nginx/conf.d",
            "docs",
        ],
    ))
    include_env_file: bool = field(default_factory=lambda: _bool("BACKUP_INCLUDE_ENV_FILE", False))

    # --- Output ---
    # Reuses the `BACKUP_DIR`/`BACKUP_RETENTION_DAYS` names already documented
    # in .env.example and docs/DEPLOY_VPS.md's host-cron backup.sh example —
    # the docker-compose "backup"/"backup-once" services override BACKUP_DIR
    # to the container's `/backups` volume mount point.
    output_dir: str = field(default_factory=lambda: _str("BACKUP_DIR", "/var/backups/visionmart"))
    retention_days: int = field(default_factory=lambda: _int("BACKUP_RETENTION_DAYS", 14))

    # --- Scheduling (used only by `backup.scheduler`, not by a one-shot `run`) ---
    cron_schedule: str = field(default_factory=lambda: _str("BACKUP_CRON_SCHEDULE", "0 2 * * *"))

    # --- Logging ---
    log_dir: str = field(default_factory=lambda: _str("BACKUP_LOG_DIR", "/data/logs"))
    log_max_bytes: int = field(default_factory=lambda: _int("BACKUP_LOG_MAX_BYTES", 10 * 1024 * 1024))
    log_backup_count: int = field(default_factory=lambda: _int("BACKUP_LOG_BACKUP_COUNT", 5))

    @property
    def postgres(self) -> PostgresDsn:
        return PostgresDsn.parse(self.database_url)


_CONFIG: BackupConfig | None = None


def get_backup_config() -> BackupConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = BackupConfig()
    return _CONFIG


def reload_backup_config() -> BackupConfig:
    global _CONFIG
    _CONFIG = BackupConfig()
    return _CONFIG
