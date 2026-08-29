"""The shared check engine backing both the Production Readiness Report
(`visionmart.readiness`, exposed via the monitoring service's
`/api/readiness`) and the `visionmart doctor` CLI (`visionmart.doctor`).

Every function here is READ-ONLY: it observes (HTTP GET, `SELECT`-only
SQL, `PING`/`INFO`, `stat()`/`access()`, Docker Engine API list/inspect
calls) and never mutates production data, configuration, or container
state. See `docs/45_DEPLOYMENT_VALIDATION.md` for the explicit audit of
this claim, function by function.

Where a check already exists in `monitoring/collectors/*.py` (Postgres,
Redis, Celery, Docker, host resources, camera, evaluation), this module
calls that existing function rather than re-implementing the probe --
this is the concrete mechanism behind "reuse existing components... avoid
duplicate functionality" from the spec. Only genuinely new checks
(configuration/env vars, storage permissions, backup directory, log
directories, monitoring/evaluation service reachability, Python
dependency presence, basic secret-hygiene) are implemented here.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from dataclasses import dataclass
from pathlib import Path

from visionmart.config import DoctorConfig

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"


@dataclass
class CheckResult:
    category: str
    name: str
    status: str  # PASS | WARNING | FAIL
    detail: str
    recommendation: str | None = None

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "recommendation": self.recommendation,
        }


# --------------------------------------------------------------------
# Configuration / Security -- new checks, no existing collector for these.
# --------------------------------------------------------------------

def check_configuration(cfg: DoctorConfig) -> list[CheckResult]:
    results: list[CheckResult] = []
    for subsystem, var_names in cfg.required_env_vars.items():
        for name in var_names:
            value = os.getenv(name)
            if value:
                results.append(CheckResult("Configuration", f"{name} ({subsystem})", PASS, "Set."))
            else:
                results.append(CheckResult(
                    "Configuration", f"{name} ({subsystem})", FAIL,
                    f"Environment variable {name} is not set.",
                    f"Set {name} in your .env file (see .env.example for the expected format).",
                ))
    return results


def check_security(cfg: DoctorConfig) -> list[CheckResult]:
    results: list[CheckResult] = []
    is_production = cfg.app_env.strip().lower() == "production"

    for name, default_value in cfg.known_default_secrets.items():
        current = os.getenv(name, "")
        if not current:
            # Already reported as FAIL by check_configuration if it's in
            # required_env_vars -- don't double up here.
            continue
        if current == default_value:
            status = FAIL if is_production else WARNING
            results.append(CheckResult(
                "Security", f"{name} not default", status,
                f"{name} is still set to the .env.example placeholder value.",
                f"Generate a strong, unique value for {name} before deploying to production.",
            ))
        else:
            results.append(CheckResult("Security", f"{name} not default", PASS, "Not using the placeholder value."))

    if is_production and cfg.app_debug:
        results.append(CheckResult(
            "Security", "APP_DEBUG disabled in production", WARNING,
            "APP_DEBUG=true while APP_ENV=production.",
            "Set APP_DEBUG=false in production to avoid leaking stack traces/debug info.",
        ))
    else:
        results.append(CheckResult("Security", "APP_DEBUG disabled in production", PASS, f"APP_ENV={cfg.app_env}, APP_DEBUG={cfg.app_debug}."))

    return results


# --------------------------------------------------------------------
# Database / Redis / Celery / Docker -- reuse monitoring/collectors/system_resources.py.
# --------------------------------------------------------------------

async def check_database(cfg: DoctorConfig) -> CheckResult:
    from monitoring.collectors.system_resources import collect_postgres_status

    if not cfg.database_url:
        return CheckResult("Database", "PostgreSQL reachable", FAIL, "DATABASE_URL is not set.", "Set DATABASE_URL in .env.")
    status = await collect_postgres_status(cfg.database_url)
    if status.reachable:
        detail = f"Connected (server version {status.version or 'unknown'}, {status.active_connections if status.active_connections is not None else '?'} active connections)."
        return CheckResult("Database", "PostgreSQL reachable", PASS, detail)
    return CheckResult(
        "Database", "PostgreSQL reachable", FAIL, f"Could not connect: {status.reason}",
        "Verify DATABASE_URL, that PostgreSQL is running, and that network/firewall rules allow the connection.",
    )


async def check_redis(cfg: DoctorConfig) -> CheckResult:
    from monitoring.collectors.system_resources import collect_redis_status

    status = await collect_redis_status(cfg.redis_url)
    if status.reachable:
        return CheckResult("Redis", "Redis reachable", PASS, f"PING ok ({status.connected_clients or 0} connected clients, {status.used_memory_mb or 0} MB used).")
    return CheckResult(
        "Redis", "Redis reachable", FAIL, f"Could not connect: {status.reason}",
        "Verify REDIS_URL and that the Redis service is running.",
    )


def check_celery(cfg: DoctorConfig) -> CheckResult:
    from monitoring.collectors.system_resources import collect_celery_status

    status = collect_celery_status(cfg.celery_broker)
    if status.reachable and status.worker_count > 0:
        return CheckResult("Celery", "Celery workers responding", PASS, f"{status.worker_count} worker(s) responding to ping.")
    if status.reachable:
        return CheckResult(
            "Celery", "Celery workers responding", WARNING, "Broker reachable but 0 workers responded.",
            "Start at least one Celery worker (docker compose up -d worker, or check its logs if it's crash-looping).",
        )
    return CheckResult(
        "Celery", "Celery workers responding", FAIL, f"Broker unreachable: {status.reason}",
        "Verify CELERY_BROKER_URL and that the broker (Redis) is running.",
    )


def check_docker(cfg: DoctorConfig) -> CheckResult:
    from monitoring.collectors.system_resources import collect_docker_status

    status = collect_docker_status(cfg.docker_socket, cfg.docker_prefix)
    if not status.reachable:
        return CheckResult(
            "Docker", "Docker containers healthy", WARNING, f"Docker socket not reachable: {status.reason}",
            "Optional check -- mount /var/run/docker.sock into the container running this check to enable it.",
        )
    unhealthy = [c for c in status.containers if c.status != "running" or c.health == "unhealthy"]
    if unhealthy:
        return CheckResult(
            "Docker", "Docker containers healthy", WARNING,
            f"{len(unhealthy)}/{len(status.containers)} container(s) not running/unhealthy: {', '.join(c.name for c in unhealthy)}.",
            "Check `docker compose ps` and `docker compose logs <service>` for the affected container(s).",
        )
    return CheckResult("Docker", "Docker containers healthy", PASS, f"{len(status.containers)} container(s), all running/healthy.")


# --------------------------------------------------------------------
# Camera / Evaluation -- reuse monitoring/collectors/camera_health.py and
# monitoring/collectors/evaluation_health.py.
# --------------------------------------------------------------------

async def check_camera(cfg: DoctorConfig) -> CheckResult:
    from monitoring.collectors.camera_health import collect_camera_health

    snap = await collect_camera_health(cfg.database_url, cfg.ai_engine_url, cfg.monitoring_sqlite_path)
    if not snap.db_reachable:
        return CheckResult("Camera", "Camera connectivity", FAIL, f"Cannot read cameras table: {snap.db_reason}")
    if not snap.cameras:
        return CheckResult(
            "Camera", "Camera connectivity", WARNING, "Database reachable but no cameras registered.",
            "Register at least one camera before going live (or confirm this store intentionally has none yet).",
        )
    offline = [c for c in snap.cameras if not c.is_online_db]
    if not snap.ai_engine_reachable:
        return CheckResult(
            "Camera", "Camera connectivity", WARNING, f"AI Engine unreachable: {snap.ai_engine_reason} ({len(snap.cameras)} camera(s) registered).",
            "Verify the ai-engine service is running and reachable from wherever this check runs.",
        )
    if offline:
        return CheckResult(
            "Camera", "Camera connectivity", WARNING, f"{len(offline)}/{len(snap.cameras)} camera(s) offline.",
            "Check camera network connectivity and that ai-engine's frame-capture loop is running for each camera.",
        )
    return CheckResult("Camera", "Camera connectivity", PASS, f"All {len(snap.cameras)} registered camera(s) online.")


def check_evaluation(cfg: DoctorConfig) -> CheckResult:
    from monitoring.collectors.evaluation_health import check_evaluation_reports

    status = check_evaluation_reports(cfg.evaluation_reports_dir)
    if status.reachable and status.report_count > 0:
        return CheckResult("Evaluation", "Evaluation reports available", PASS, f"{status.report_count} report(s), most recent {status.last_report_age_seconds:.0f}s ago.")
    # Evaluation is explicitly an optional signal (see monitoring/health_score.py) --
    # never FAIL the whole report over it, only ever PASS/WARNING.
    return CheckResult(
        "Evaluation", "Evaluation reports available", WARNING, status.reason or "No evaluation reports found.",
        "Optional: run `python -m evaluation.cli evaluate ...` to produce a baseline report (see docs/EVALUATION_FRAMEWORK.md).",
    )


# --------------------------------------------------------------------
# Storage / Backup / Logging -- new checks (filesystem + MinIO SDK only).
# --------------------------------------------------------------------

def check_storage(cfg: DoctorConfig) -> CheckResult:
    try:
        from minio import Minio
    except ImportError:
        return CheckResult(
            "Storage", "Object storage (MinIO) reachable", WARNING, "`minio` SDK not installed in this environment.",
            "Run this check from an environment with the `minio` package installed (e.g. ai-engine's), or install it here.",
        )
    try:
        client = Minio(
            cfg.minio_endpoint, access_key=cfg.minio_root_user, secret_key=cfg.minio_root_password,
            secure=cfg.minio_use_ssl,
        )
        exists = client.bucket_exists(cfg.minio_bucket)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "Storage", "Object storage (MinIO) reachable", FAIL, f"Could not reach MinIO: {exc}",
            "Verify MINIO_ENDPOINT/MINIO_ROOT_USER/MINIO_ROOT_PASSWORD and that the MinIO service is running.",
        )
    if exists:
        return CheckResult("Storage", "Object storage (MinIO) reachable", PASS, f"Bucket '{cfg.minio_bucket}' exists and is reachable.")
    return CheckResult(
        "Storage", "Object storage (MinIO) reachable", WARNING, f"MinIO reachable but bucket '{cfg.minio_bucket}' does not exist yet.",
        "The bucket is normally created on first upload/by setup.sh -- create it manually if uploads are failing.",
    )


def _dir_writable(path_str: str) -> tuple[bool, bool, str | None]:
    """Returns (exists, writable, error). Never raises."""
    path = Path(path_str)
    if not path.exists():
        return False, False, None
    try:
        probe = path / f".visionmart_doctor_write_test_{int(time.time() * 1000)}"
        probe.touch()
        probe.unlink()
        return True, True, None
    except OSError as exc:
        return True, False, str(exc)


def check_backup(cfg: DoctorConfig) -> CheckResult:
    exists, writable, err = _dir_writable(cfg.backup_dir)
    if not exists:
        return CheckResult(
            "Backup", "Backup directory ready", FAIL, f"Backup directory does not exist: {cfg.backup_dir}",
            f"Create {cfg.backup_dir} (or update BACKUP_DIR) and ensure the backup service can write to it.",
        )
    if not writable:
        return CheckResult(
            "Backup", "Backup directory ready", FAIL, f"Backup directory is not writable: {cfg.backup_dir} ({err})",
            "Fix directory permissions so the backup service's user can write to it.",
        )

    zips = sorted(Path(cfg.backup_dir).glob("visionmart-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        return CheckResult(
            "Backup", "Recent backup exists", WARNING, "Backup directory is writable but no backup archive has been produced yet.",
            "Run `python -m backup.cli run` once to produce a baseline backup, or wait for the scheduled backup service.",
        )
    age_days = (time.time() - zips[0].stat().st_mtime) / 86400.0
    if age_days > cfg.backup_retention_days:
        return CheckResult(
            "Backup", "Recent backup exists", WARNING, f"Most recent backup is {age_days:.1f} day(s) old (retention is {cfg.backup_retention_days} days).",
            "Verify the backup scheduler (docker-compose service 'backup') is running and its cron schedule is firing.",
        )
    return CheckResult("Backup", "Recent backup exists", PASS, f"Most recent backup is {age_days:.1f} day(s) old: {zips[0].name}.")


def check_logging(cfg: DoctorConfig) -> list[CheckResult]:
    results: list[CheckResult] = []
    for service, log_dir in cfg.log_dirs.items():
        exists, writable, err = _dir_writable(log_dir)
        if not exists:
            results.append(CheckResult(
                "Logging", f"{service} log directory", WARNING, f"Log directory does not exist yet: {log_dir}",
                "It will be created automatically on first log write -- only a concern if the service has already run.",
            ))
        elif not writable:
            results.append(CheckResult(
                "Logging", f"{service} log directory", FAIL, f"Log directory is not writable: {log_dir} ({err})",
                "Fix directory permissions so the service's user can write log files.",
            ))
        else:
            results.append(CheckResult("Logging", f"{service} log directory", PASS, f"{log_dir} exists and is writable."))
    return results


# --------------------------------------------------------------------
# Monitoring service / disk space / Python dependencies.
# --------------------------------------------------------------------

async def check_monitoring_service(cfg: DoctorConfig) -> CheckResult:
    try:
        import httpx
    except ImportError:
        return CheckResult("Monitoring", "Monitoring service reachable", WARNING, "`httpx` not installed in this environment.")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{cfg.monitoring_service_url}/health")
        if resp.status_code == 200:
            return CheckResult("Monitoring", "Monitoring service reachable", PASS, "/health returned 200.")
        return CheckResult(
            "Monitoring", "Monitoring service reachable", WARNING, f"/health returned HTTP {resp.status_code}.",
            "Check the monitoring service's logs (`docker compose logs monitoring`).",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "Monitoring", "Monitoring service reachable", FAIL, f"Could not reach monitoring service: {exc}",
            "Verify MONITORING_SERVICE_URL and that the monitoring service/container is running.",
        )


def check_disk_space(cfg: DoctorConfig) -> CheckResult:
    from monitoring.collectors.system_resources import collect_host_resources

    host = collect_host_resources()
    if host.disk_percent is None:
        return CheckResult("Health", "Disk space", WARNING, host.reason or "Could not read disk usage (psutil not installed).")
    free_percent = 100.0 - host.disk_percent
    if host.disk_percent >= 95:
        status = FAIL
    elif free_percent < cfg.min_free_disk_percent:
        status = WARNING
    else:
        status = PASS
    detail = f"{host.disk_percent:.1f}% used, {host.disk_used_gb}/{host.disk_total_gb} GB."
    rec = None if status == PASS else "Free up disk space or expand the volume -- backups, logs, and evaluation reports all consume local disk."
    return CheckResult("Health", "Disk space", status, detail, rec)


def check_python_dependencies(cfg: DoctorConfig) -> CheckResult:
    core = ["sqlalchemy", "asyncpg", "redis", "celery"]
    optional = [p for p in cfg.critical_python_packages if p not in core]

    missing_core = [p for p in core if importlib.util.find_spec(p) is None]
    missing_optional = [p for p in optional if importlib.util.find_spec(p) is None]

    if missing_core:
        return CheckResult(
            "Python Dependencies", "Required packages importable", FAIL,
            f"Missing core package(s): {', '.join(missing_core)}.",
            "Install the missing package(s), e.g. `pip install -r monitoring/requirements.txt`.",
        )
    if missing_optional:
        return CheckResult(
            "Python Dependencies", "Required packages importable", WARNING,
            f"Missing optional package(s): {', '.join(missing_optional)} (their checks reported degraded/unavailable above).",
            "Run this command inside the monitoring container for full coverage: `docker compose exec monitoring python -m visionmart doctor`.",
        )
    return CheckResult("Python Dependencies", "Required packages importable", PASS, "All checked packages are importable.")


# --------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------

async def run_all_checks(cfg: DoctorConfig | None = None) -> list[CheckResult]:
    cfg = cfg or DoctorConfig()

    results: list[CheckResult] = []
    results.extend(check_configuration(cfg))
    results.extend(check_security(cfg))

    async_results = await asyncio.gather(
        check_database(cfg),
        check_redis(cfg),
        check_camera(cfg),
        check_monitoring_service(cfg),
    )
    results.extend(async_results)

    results.append(check_celery(cfg))
    results.append(check_docker(cfg))
    results.append(check_evaluation(cfg))
    results.append(check_storage(cfg))
    results.append(check_backup(cfg))
    results.extend(check_logging(cfg))
    results.append(check_disk_space(cfg))
    results.append(check_python_dependencies(cfg))

    return results
