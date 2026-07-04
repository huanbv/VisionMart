"""Configurable alert rules.

Each rule is a pure function `snapshots -> list[(subject, message)]`
evaluated against the latest collector output (`{"camera": ..., "ai_pipeline":
..., "system": ..., "backend_health": ..., "ai_engine_health": ...}`, the
same dicts `monitoring/scheduler.py` gathers every poll). A rule that
returns an empty list is "not currently triggered" for every subject; the
Alert Engine (`engine.py`) diffs this against what was active last poll to
auto-resolve alerts whose condition has cleared.

All thresholds come from `MonitoringConfig` (env-configurable — see
`monitoring/config.py`), per requirement 5 ("configurable warnings").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from monitoring.config import MonitoringConfig

Evaluator = Callable[[dict], list[tuple[str, str]]]


@dataclass(frozen=True)
class AlertRule:
    rule_id: str
    description: str
    severity: str  # "critical" | "warning" | "info"
    evaluate: Evaluator


def build_default_rules(cfg: MonitoringConfig) -> list[AlertRule]:
    rules: list[AlertRule] = []

    def camera_offline(snapshots: dict) -> list[tuple[str, str]]:
        out = []
        cam = snapshots.get("camera") or {}
        for c in cam.get("cameras", []):
            seconds = c.get("seconds_since_last_seen")
            if not c.get("is_online_db") and seconds is not None and seconds >= cfg.alert_camera_offline_grace_seconds:
                out.append((c["camera_id"], f"Camera '{c.get('name')}' ({c.get('code')}) offline for {int(seconds)}s (last seen {c.get('last_seen_at')})."))
        return out

    rules.append(AlertRule("camera_offline", "Camera offline beyond grace period", "critical", camera_offline))

    def low_camera_fps(snapshots: dict) -> list[tuple[str, str]]:
        out = []
        cam = snapshots.get("camera") or {}
        for c in cam.get("cameras", []):
            fps = c.get("fps")
            if c.get("is_online_db") and fps is not None and fps < cfg.alert_min_fps:
                out.append((c["camera_id"], f"Camera '{c.get('name')}' ({c.get('code')}) FPS is {fps:.2f}, below {cfg.alert_min_fps}."))
        return out

    rules.append(AlertRule("low_camera_fps", "Camera FPS below minimum threshold", "warning", low_camera_fps))

    def high_cpu(snapshots: dict) -> list[tuple[str, str]]:
        sysres = snapshots.get("system") or {}
        cpu = (sysres.get("host") or {}).get("cpu_percent")
        if cpu is not None and cpu >= cfg.alert_cpu_percent:
            return [("host", f"CPU usage at {cpu:.1f}%, threshold {cfg.alert_cpu_percent}%.")]
        return []

    rules.append(AlertRule("high_cpu", "Host CPU usage above threshold", "warning", high_cpu))

    def high_ram(snapshots: dict) -> list[tuple[str, str]]:
        sysres = snapshots.get("system") or {}
        ram = (sysres.get("host") or {}).get("ram_percent")
        if ram is not None and ram >= cfg.alert_ram_percent:
            return [("host", f"RAM usage at {ram:.1f}%, threshold {cfg.alert_ram_percent}%.")]
        return []

    rules.append(AlertRule("high_ram", "Host RAM usage above threshold", "warning", high_ram))

    def low_disk(snapshots: dict) -> list[tuple[str, str]]:
        sysres = snapshots.get("system") or {}
        disk = (sysres.get("host") or {}).get("disk_percent")
        if disk is not None and disk >= cfg.alert_disk_percent:
            return [("host", f"Disk usage at {disk:.1f}%, threshold {cfg.alert_disk_percent}%.")]
        return []

    rules.append(AlertRule("low_disk_space", "Host disk usage above threshold", "critical", low_disk))

    def excessive_latency(snapshots: dict) -> list[tuple[str, str]]:
        pipe = snapshots.get("ai_pipeline") or {}
        total_ms = pipe.get("pipeline_total_ms")
        if total_ms is not None and total_ms >= cfg.alert_pipeline_latency_ms:
            return [("ai_pipeline", f"Pipeline total latency at {total_ms:.1f}ms, threshold {cfg.alert_pipeline_latency_ms}ms.")]
        return []

    rules.append(AlertRule("excessive_pipeline_latency", "AI pipeline latency above threshold", "warning", excessive_latency))

    def celery_worker_failure(snapshots: dict) -> list[tuple[str, str]]:
        sysres = snapshots.get("system") or {}
        celery = sysres.get("celery") or {}
        if not celery.get("reachable") or celery.get("worker_count", 0) == 0:
            reason = celery.get("reason") or "No workers responded."
            return [("celery", f"No healthy Celery workers detected: {reason}")]
        return []

    rules.append(AlertRule("celery_worker_failure", "No healthy Celery workers", "critical", celery_worker_failure))

    def redis_down(snapshots: dict) -> list[tuple[str, str]]:
        sysres = snapshots.get("system") or {}
        redis_status = sysres.get("redis") or {}
        if not redis_status.get("reachable"):
            return [("redis", f"Redis unreachable: {redis_status.get('reason')}")]
        return []

    rules.append(AlertRule("redis_down", "Redis unreachable", "critical", redis_down))

    def postgres_down(snapshots: dict) -> list[tuple[str, str]]:
        sysres = snapshots.get("system") or {}
        pg = sysres.get("postgres") or {}
        if not pg.get("reachable"):
            return [("postgres", f"PostgreSQL unreachable: {pg.get('reason')}")]
        return []

    rules.append(AlertRule("postgres_down", "PostgreSQL unreachable", "critical", postgres_down))

    def backend_unreachable(snapshots: dict) -> list[tuple[str, str]]:
        h = snapshots.get("backend_health") or {}
        if not h.get("ok"):
            return [("backend", f"Backend /health check failing: {h.get('reason')}")]
        return []

    rules.append(AlertRule("backend_unreachable", "Backend service /health failing", "critical", backend_unreachable))

    def ai_engine_unreachable(snapshots: dict) -> list[tuple[str, str]]:
        h = snapshots.get("ai_engine_health") or {}
        if not h.get("ok"):
            return [("ai-engine", f"AI Engine /health check failing: {h.get('reason')}")]
        return []

    rules.append(AlertRule("ai_engine_unreachable", "AI Engine service /health failing", "critical", ai_engine_unreachable))

    def docker_container_unhealthy(snapshots: dict) -> list[tuple[str, str]]:
        out = []
        docker_status = (snapshots.get("system") or {}).get("docker") or {}
        if not docker_status.get("reachable"):
            return out
        for c in docker_status.get("containers", []):
            if c.get("status") != "running" or c.get("health") == "unhealthy":
                out.append((c["name"], f"Container '{c['name']}' status={c.get('status')} health={c.get('health')}."))
        return out

    rules.append(AlertRule("docker_container_unhealthy", "Docker container not running / unhealthy", "critical", docker_container_unhealthy))

    return rules
