"""System resource monitoring: host CPU/RAM/GPU/disk, Docker containers,
Celery workers, Redis, and PostgreSQL.

Every check here is either a local host read (`psutil`/`pynvml`) or a
lightweight, read-only probe against an existing service using only its
already-public interface — nothing here imports `backend.app.*` or
`ai_engine.app.*`:

  - **Celery workers**: a throwaway `Celery(broker=..., backend=...)`
    client is created just to call `.control.inspect()` over the existing
    broker connection. It does not import `app.workers.celery_app` or any
    task module, so it cannot accidentally register or trigger tasks.
  - **Redis**: a plain `redis.asyncio` client against `REDIS_URL`
    (`PING` + `INFO`).
  - **PostgreSQL**: a plain SQLAlchemy Core connection against
    `DATABASE_URL` (`SELECT 1` + `pg_stat_activity` connection count) —
    no ORM models imported.
  - **Docker containers**: the Docker Engine API via the `docker` SDK,
    reachable only if the monitoring container is given access to
    `/var/run/docker.sock` (see `docs/MONITORING.md` for the deployment
    note) — never assumed, always checked and reported honestly if
    unavailable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class HostResources:
    cpu_percent: float | None
    ram_percent: float | None
    ram_used_gb: float | None
    ram_total_gb: float | None
    disk_percent: float | None
    disk_used_gb: float | None
    disk_total_gb: float | None
    gpu_available: bool
    gpu_util_percent: float | None
    gpu_mem_used_mb: float | None
    gpu_mem_total_mb: float | None
    reason: str | None = None


@dataclass
class ContainerStatus:
    name: str
    status: str
    health: str | None
    cpu_percent: float | None
    mem_usage_mb: float | None
    restart_count: int | None


@dataclass
class DockerStatus:
    reachable: bool
    reason: str | None
    containers: list[ContainerStatus] = field(default_factory=list)


@dataclass
class CeleryStatus:
    reachable: bool
    reason: str | None
    worker_count: int
    workers: dict[str, dict]  # worker name -> {"active": n, "reserved": n}


@dataclass
class RedisStatus:
    reachable: bool
    reason: str | None
    used_memory_mb: float | None
    connected_clients: int | None


@dataclass
class PostgresStatus:
    reachable: bool
    reason: str | None
    active_connections: int | None
    version: str | None = None


@dataclass
class SystemResourceSnapshot:
    checked_at: float
    host: HostResources
    docker: DockerStatus
    celery: CeleryStatus
    redis: RedisStatus
    postgres: PostgresStatus

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "host": vars(self.host),
            "docker": {
                "reachable": self.docker.reachable, "reason": self.docker.reason,
                "containers": [vars(c) for c in self.docker.containers],
            },
            "celery": vars(self.celery),
            "redis": vars(self.redis),
            "postgres": vars(self.postgres),
        }


def collect_host_resources() -> HostResources:
    try:
        import psutil
    except ImportError:
        return HostResources(
            None, None, None, None, None, None, None, False, None, None, None,
            reason="psutil not installed in the monitoring service's environment.",
        )

    cpu = psutil.cpu_percent(interval=0.2)
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    gpu_available = False
    gpu_util = gpu_mem_used = gpu_mem_total = None
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        gpu_available = True
        gpu_util = float(util.gpu)
        gpu_mem_used = round(mem.used / (1024 * 1024), 1)
        gpu_mem_total = round(mem.total / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 — no GPU, no driver, or no pynvml; all equally "not available"
        gpu_available = False

    return HostResources(
        cpu_percent=cpu,
        ram_percent=vm.percent,
        ram_used_gb=round(vm.used / (1024**3), 2),
        ram_total_gb=round(vm.total / (1024**3), 2),
        disk_percent=disk.percent,
        disk_used_gb=round(disk.used / (1024**3), 2),
        disk_total_gb=round(disk.total / (1024**3), 2),
        gpu_available=gpu_available,
        gpu_util_percent=gpu_util,
        gpu_mem_used_mb=gpu_mem_used,
        gpu_mem_total_mb=gpu_mem_total,
    )


def collect_docker_status(socket_url: str, name_prefix: str) -> DockerStatus:
    try:
        import docker
    except ImportError:
        return DockerStatus(reachable=False, reason="`docker` SDK not installed in the monitoring service's environment.")

    try:
        client = docker.DockerClient(base_url=socket_url)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return DockerStatus(
            reachable=False,
            reason=f"Docker socket not reachable ({exc}). Mount /var/run/docker.sock into the monitoring container to enable this check.",
        )

    containers: list[ContainerStatus] = []
    try:
        for c in client.containers.list(all=True):
            if name_prefix and not c.name.startswith(name_prefix):
                continue
            cpu_pct = None
            mem_mb = None
            try:
                stats = c.stats(stream=False)
                cpu_pct = _docker_cpu_percent(stats)
                mem_mb = round(stats.get("memory_stats", {}).get("usage", 0) / (1024 * 1024), 1)
            except Exception:  # noqa: BLE001 — stats can fail for a just-stopped container; not fatal
                pass
            health = None
            state = c.attrs.get("State", {})
            if "Health" in state:
                health = state["Health"].get("Status")
            restart_count = c.attrs.get("RestartCount")
            containers.append(
                ContainerStatus(
                    name=c.name, status=c.status, health=health,
                    cpu_percent=cpu_pct, mem_usage_mb=mem_mb, restart_count=restart_count,
                )
            )
    finally:
        client.close()

    return DockerStatus(reachable=True, reason=None, containers=containers)


def _docker_cpu_percent(stats: dict) -> float | None:
    try:
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        online_cpus = stats["cpu_stats"].get("online_cpus") or len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
        if system_delta > 0 and cpu_delta >= 0:
            return round((cpu_delta / system_delta) * online_cpus * 100.0, 1)
    except (KeyError, ZeroDivisionError, TypeError):
        pass
    return None


def collect_celery_status(broker_url: str, timeout_seconds: float = 3.0) -> CeleryStatus:
    try:
        from celery import Celery

        app = Celery("visionmart-monitor", broker=broker_url)
        inspector = app.control.inspect(timeout=timeout_seconds)
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        pings = inspector.ping() or {}
    except Exception as exc:  # noqa: BLE001
        return CeleryStatus(reachable=False, reason=str(exc), worker_count=0, workers={})

    if not pings:
        return CeleryStatus(
            reachable=False,
            reason="Broker reachable but no Celery workers responded to ping (all workers may be down).",
            worker_count=0, workers={},
        )

    workers = {}
    for name in pings:
        workers[name] = {
            "active": len(active.get(name, [])),
            "reserved": len(reserved.get(name, [])),
        }
    return CeleryStatus(reachable=True, reason=None, worker_count=len(pings), workers=workers)


async def collect_redis_status(redis_url: str) -> RedisStatus:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, socket_timeout=5)
        try:
            await client.ping()
            info = await client.info(section="memory")
            clients_info = await client.info(section="clients")
            return RedisStatus(
                reachable=True, reason=None,
                used_memory_mb=round(info.get("used_memory", 0) / (1024 * 1024), 1),
                connected_clients=clients_info.get("connected_clients"),
            )
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        return RedisStatus(reachable=False, reason=str(exc), used_memory_mb=None, connected_clients=None)


async def collect_postgres_status(database_url: str) -> PostgresStatus:
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                try:
                    result = await conn.execute(text("SELECT count(*) AS n FROM pg_stat_activity"))
                    active_connections = result.scalar_one()
                except Exception:  # noqa: BLE001 — pg_stat_activity may be restricted for this role
                    active_connections = None
                try:
                    version_result = await conn.execute(text("SHOW server_version"))
                    version = version_result.scalar_one()
                except Exception:  # noqa: BLE001 — cosmetic only, never fail the health check over it
                    version = None
            return PostgresStatus(reachable=True, reason=None, active_connections=active_connections, version=version)
        finally:
            await engine.dispose()
    except Exception as exc:  # noqa: BLE001
        return PostgresStatus(reachable=False, reason=str(exc), active_connections=None, version=None)


async def collect_system_resources(
    database_url: str,
    redis_url: str,
    celery_broker_url: str,
    docker_socket: str,
    docker_prefix: str,
) -> SystemResourceSnapshot:
    now = time.time()
    host = collect_host_resources()
    docker_status = collect_docker_status(docker_socket, docker_prefix)
    celery_status = collect_celery_status(celery_broker_url)
    redis_status = await collect_redis_status(redis_url)
    postgres_status = await collect_postgres_status(database_url)
    return SystemResourceSnapshot(
        checked_at=now, host=host, docker=docker_status,
        celery=celery_status, redis=redis_status, postgres=postgres_status,
    )
