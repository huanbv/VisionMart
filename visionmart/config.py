"""Environment-driven configuration for `visionmart` checks.

Deliberately mirrors the tiny `_str`/`_int`/`_bool` env-parsing helpers
already duplicated in `monitoring/config.py`, `backup/config.py`, and
`evaluation/logging_config.py` -- kept as a small, independent copy
(rather than a shared import) so this package has zero import-time
dependency on any other package's config module, matching the pattern
already established across the project.

Every field defaults to the SAME value documented in `.env.example` for
the corresponding service, so a `visionmart doctor` run with no special
setup checks the same things a real deployment would use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


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


# Secrets whose `.env.example` placeholder value must never survive into a
# real production deployment unchanged -- checked by `checks.check_security`.
_KNOWN_DEFAULT_SECRETS = {
    "BACKEND_SECRET_KEY": "change-me-please-generate-a-strong-secret",
    "MONITORING_API_TOKEN": "change-me-monitoring-token",
    "MINIO_ROOT_PASSWORD": "visionmart-minio",
}

# Environment variables `checks.check_configuration` verifies are set to
# *something* (not necessarily non-default -- that's `check_security`'s
# job). Grouped by the subsystem that owns them, purely for readable
# check names; the check itself doesn't care about the grouping.
_REQUIRED_ENV_VARS = {
    "Database": ["DATABASE_URL"],
    "Redis": ["REDIS_URL"],
    "Celery": ["CELERY_BROKER_URL"],
    "Backend": ["BACKEND_SECRET_KEY", "BACKEND_CORS_ORIGINS"],
    "Storage": ["MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "MINIO_BUCKET"],
    "Backup": ["BACKUP_DIR", "BACKUP_RETENTION_DAYS"],
    "Monitoring": ["MONITORING_API_TOKEN", "MONITORING_SERVICE_URL"],
}

# Third-party packages this package's own checks (and the collectors they
# call) rely on being importable -- reported per-package rather than
# assumed, since `visionmart doctor` may be invoked from a Python
# environment that only has a subset installed (e.g. backend's venv lacks
# `docker`/`psutil`; see visionmart/__init__.py's module docstring for the
# recommended "run inside the monitoring container" invocation).
_CRITICAL_PYTHON_PACKAGES = [
    "sqlalchemy",
    "asyncpg",
    "redis",
    "celery",
    "docker",
    "psutil",
]


@dataclass(frozen=True)
class DoctorConfig:
    database_url: str = field(default_factory=lambda: _str("DATABASE_URL", ""))
    redis_url: str = field(default_factory=lambda: _str("REDIS_URL", "redis://redis:6379/0"))
    celery_broker_url: str = field(default_factory=lambda: _str("CELERY_BROKER_URL", ""))
    docker_socket: str = field(default_factory=lambda: _str("MONITORING_DOCKER_SOCKET", "unix://var/run/docker.sock"))
    docker_prefix: str = field(default_factory=lambda: _str("MONITORING_DOCKER_PREFIX", "visionmart-"))
    ai_engine_url: str = field(default_factory=lambda: _str("MONITORING_AI_ENGINE_URL", "http://ai-engine:8100"))
    monitoring_sqlite_path: str = field(default_factory=lambda: _str("MONITORING_SQLITE_PATH", "/data/monitoring.db"))

    monitoring_service_url: str = field(default_factory=lambda: _str("MONITORING_SERVICE_URL", "http://monitoring:8200"))
    monitoring_api_token: str = field(default_factory=lambda: _str("MONITORING_API_TOKEN", "change-me-monitoring-token"))

    evaluation_reports_dir: str = field(default_factory=lambda: _str("MONITORING_EVALUATION_REPORTS_DIR", "/app/repo/evaluation_results"))

    backup_dir: str = field(default_factory=lambda: _str("BACKUP_DIR", "/var/backups/visionmart"))
    backup_retention_days: int = field(default_factory=lambda: _int("BACKUP_RETENTION_DAYS", 14))

    # Log directories per standalone service -- Docker-driver-covered
    # services (backend/ai-engine/celery/frontend/nginx) are rotated via
    # docker-compose.yml's "local" logging driver instead (see
    # docs/18_LOGGING.md), so only the 3 standalone Python services that
    # write their own log FILES are checked here.
    log_dirs: dict[str, str] = field(default_factory=lambda: {
        "monitoring": _str("MONITORING_LOG_DIR", "/data/logs"),
        "backup": _str("BACKUP_LOG_DIR", "/data/logs"),
        "evaluation": _str("EVALUATION_LOG_DIR", "evaluation_results/logs"),
    })

    minio_endpoint: str = field(default_factory=lambda: _str("MINIO_ENDPOINT", "minio:9000"))
    minio_root_user: str = field(default_factory=lambda: _str("MINIO_ROOT_USER", "visionmart"))
    minio_root_password: str = field(default_factory=lambda: _str("MINIO_ROOT_PASSWORD", "visionmart-minio"))
    minio_bucket: str = field(default_factory=lambda: _str("MINIO_BUCKET", "visionmart"))
    minio_use_ssl: bool = field(default_factory=lambda: _bool("MINIO_USE_SSL", False))

    app_env: str = field(default_factory=lambda: _str("APP_ENV", "development"))
    app_debug: bool = field(default_factory=lambda: _bool("APP_DEBUG", True))

    min_free_disk_percent: float = field(default_factory=lambda: 100.0 - _int("MONITORING_ALERT_DISK_PERCENT", 85))

    required_env_vars: dict[str, list[str]] = field(default_factory=lambda: dict(_REQUIRED_ENV_VARS))
    known_default_secrets: dict[str, str] = field(default_factory=lambda: dict(_KNOWN_DEFAULT_SECRETS))
    critical_python_packages: list[str] = field(default_factory=lambda: list(_CRITICAL_PYTHON_PACKAGES))


    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url


def get_doctor_config() -> DoctorConfig:
    return DoctorConfig()
