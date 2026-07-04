"""Environment-driven configuration for the monitoring service.

Every value has a safe default so the service starts (and degrades
gracefully, reporting "not reachable" per-collector) even if some of the
optional integrations (Docker socket, GPU, etc.) aren't available in a
given deployment.
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


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class MonitoringConfig:
    # --- Targets to observe (all read-only HTTP/SQL/TCP calls) ---
    backend_url: str = field(default_factory=lambda: _str("MONITORING_BACKEND_URL", "http://backend:8000"))
    ai_engine_url: str = field(default_factory=lambda: _str("MONITORING_AI_ENGINE_URL", "http://ai-engine:8100"))
    database_url: str = field(default_factory=lambda: _str("DATABASE_URL", ""))
    redis_url: str = field(default_factory=lambda: _str("REDIS_URL", "redis://redis:6379/0"))
    celery_broker_url: str = field(default_factory=lambda: _str("CELERY_BROKER_URL", ""))
    docker_socket: str = field(default_factory=lambda: _str("MONITORING_DOCKER_SOCKET", "unix://var/run/docker.sock"))
    docker_container_prefix: str = field(default_factory=lambda: _str("MONITORING_DOCKER_PREFIX", "visionmart-"))
    # Optional signal for the Health Score / Production Readiness Report
    # ("Evaluation (optional)"). Requires the read-only repo mount on the
    # "monitoring" docker-compose service (`.:/app/repo:ro`) — if absent,
    # this simply reports "not reachable", never raises.
    evaluation_reports_dir: str = field(default_factory=lambda: _str("MONITORING_EVALUATION_REPORTS_DIR", "/app/repo/evaluation_results"))
    # Same read-only repo mount, used to read release_info.json (see
    # scripts/generate_release_info.py and monitoring/collectors/release_info.py).
    repo_root: str = field(default_factory=lambda: _str("MONITORING_REPO_ROOT", "/app/repo"))

    # --- This service's own auth (never the app's user auth system) ---
    api_token: str = field(default_factory=lambda: _str("MONITORING_API_TOKEN", "change-me-monitoring-token"))

    # --- Polling / storage ---
    poll_interval_seconds: int = field(default_factory=lambda: _int("MONITORING_POLL_INTERVAL_SECONDS", 30))
    sqlite_path: str = field(default_factory=lambda: _str("MONITORING_SQLITE_PATH", "/data/monitoring.db"))
    retention_days: int = field(default_factory=lambda: _int("MONITORING_RETENTION_DAYS", 30))
    log_dir: str = field(default_factory=lambda: _str("MONITORING_LOG_DIR", "/data/logs"))
    log_max_bytes: int = field(default_factory=lambda: _int("MONITORING_LOG_MAX_BYTES", 10 * 1024 * 1024))
    log_backup_count: int = field(default_factory=lambda: _int("MONITORING_LOG_BACKUP_COUNT", 5))

    # --- Alert thresholds (all configurable; see alerts/rules.py for how they're used) ---
    alert_cpu_percent: float = field(default_factory=lambda: _float("MONITORING_ALERT_CPU_PERCENT", 90.0))
    alert_ram_percent: float = field(default_factory=lambda: _float("MONITORING_ALERT_RAM_PERCENT", 90.0))
    alert_disk_percent: float = field(default_factory=lambda: _float("MONITORING_ALERT_DISK_PERCENT", 85.0))
    alert_pipeline_latency_ms: float = field(default_factory=lambda: _float("MONITORING_ALERT_PIPELINE_LATENCY_MS", 1000.0))
    alert_camera_offline_grace_seconds: int = field(default_factory=lambda: _int("MONITORING_ALERT_CAMERA_OFFLINE_GRACE_SECONDS", 120))
    alert_min_fps: float = field(default_factory=lambda: _float("MONITORING_ALERT_MIN_FPS", 1.0))

    # --- Optional webhook notifier (Slack/Discord/generic JSON webhook) ---
    webhook_url: str = field(default_factory=lambda: _str("MONITORING_WEBHOOK_URL", ""))

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url


_CONFIG: MonitoringConfig | None = None


def get_monitoring_config() -> MonitoringConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = MonitoringConfig()
    return _CONFIG


def reload_monitoring_config() -> MonitoringConfig:
    global _CONFIG
    _CONFIG = MonitoringConfig()
    return _CONFIG
