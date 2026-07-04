"""Global System Health Score — a single 0-100 number + status label
aggregated purely from data the existing collectors already gather each
poll (`monitoring/scheduler.py`'s `snapshots` dict: `backend_health`,
`ai_engine_health`, `camera`, `ai_pipeline`, `system`, and optionally
`evaluation`). This module adds no new data collection of its own — per
requirement 7 ("Health Score must only aggregate existing metrics") —
it only interprets numbers `monitoring/collectors/*.py` already produced.

Scoring is a simple, auditable weighted-deduction model (not a black
box): start at 100, subtract a fixed weight for each unhealthy
component, floor at 0. Every deduction is recorded in `reasoning` so the
score is always explainable, matching the honesty/transparency pattern
used throughout `monitoring/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Status labels, in the exact vocabulary requested: Healthy / Warning /
# Critical / Degraded / Offline.
HEALTHY = "Healthy"
WARNING = "Warning"
DEGRADED = "Degraded"
CRITICAL = "Critical"
OFFLINE = "Offline"

# Component-level statuses shown in the breakdown (e.g. "Camera: OK").
OK = "OK"
COMP_WARNING = "WARNING"
COMP_CRITICAL = "CRITICAL"
NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass
class HealthScoreResult:
    score: int
    status: str
    components: dict[str, str]
    reasoning: list[str]
    generated_at: float

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "status": self.status,
            "components": self.components,
            "reasoning": self.reasoning,
            "generated_at": self.generated_at,
        }


def _status_for_score(score: int, core_down: bool) -> str:
    if core_down:
        return OFFLINE
    if score >= 90:
        return HEALTHY
    if score >= 75:
        return WARNING
    if score >= 50:
        return DEGRADED
    if score >= 25:
        return CRITICAL
    return OFFLINE


def compute_health_score(snapshots: dict, alert_cfg: "MonitoringConfig | None" = None) -> HealthScoreResult:  # noqa: F821
    """`snapshots` is the same dict `monitoring/scheduler.py` builds each
    poll (and the same dict passed to `AlertEngine.evaluate`). Thresholds
    default to the module's own conservative constants but can be
    overridden by passing the running `MonitoringConfig` (so the score
    stays consistent with the Alert Engine's own thresholds — see
    `monitoring/alerts/rules.py`)."""
    import time

    from monitoring.config import get_monitoring_config

    cfg = alert_cfg or get_monitoring_config()

    score = 100
    components: dict[str, str] = {}
    reasoning: list[str] = []

    def deduct(points: int, reason: str) -> None:
        nonlocal score
        score -= points
        reasoning.append(f"-{points}: {reason}")

    # --- Backend ---
    backend = snapshots.get("backend_health") or {}
    if backend.get("ok"):
        components["Backend"] = OK
    else:
        components["Backend"] = COMP_CRITICAL
        deduct(30, f"Backend unreachable: {backend.get('reason') or 'unknown reason'}.")

    # --- AI Engine ---
    ai_engine = snapshots.get("ai_engine_health") or {}
    if ai_engine.get("ok"):
        components["AI Engine"] = HEALTHY
    else:
        components["AI Engine"] = COMP_CRITICAL
        deduct(25, f"AI Engine unreachable: {ai_engine.get('reason') or 'unknown reason'}.")

    # --- System resources: postgres / redis / celery / docker / cpu / ram / disk / gpu ---
    system = snapshots.get("system") or {}
    postgres = system.get("postgres") or {}
    if postgres.get("reachable"):
        components["PostgreSQL"] = OK
    else:
        components["PostgreSQL"] = COMP_CRITICAL
        deduct(25, f"PostgreSQL unreachable: {postgres.get('reason') or 'unknown reason'}.")

    redis_status = system.get("redis") or {}
    if redis_status.get("reachable"):
        components["Redis"] = OK
    else:
        components["Redis"] = COMP_CRITICAL
        deduct(15, f"Redis unreachable: {redis_status.get('reason') or 'unknown reason'}.")

    celery_status = system.get("celery") or {}
    if celery_status.get("reachable") and celery_status.get("worker_count", 0) > 0:
        components["Celery"] = OK
    else:
        components["Celery"] = COMP_CRITICAL
        deduct(15, f"No healthy Celery workers: {celery_status.get('reason') or 'no workers responded'}.")

    docker_status = system.get("docker") or {}
    if not docker_status.get("reachable"):
        # Docker-socket access is an explicitly optional check (commented
        # out by default in docker-compose.yml) — not penalized, just
        # reported as not configured rather than counted against health.
        components["Docker"] = NOT_CONFIGURED
    else:
        unhealthy = [
            c for c in docker_status.get("containers", [])
            if c.get("status") != "running" or c.get("health") == "unhealthy"
        ]
        if unhealthy:
            components["Docker"] = COMP_WARNING
            deduct(min(15, 5 * len(unhealthy)), f"{len(unhealthy)} container(s) not running/unhealthy: {', '.join(c['name'] for c in unhealthy)}.")
        else:
            components["Docker"] = OK

    host = system.get("host") or {}
    cpu = host.get("cpu_percent")
    if cpu is None:
        components["CPU"] = "n/a"
    else:
        components["CPU"] = f"{cpu:.0f}%"
        if cpu >= cfg.alert_cpu_percent:
            deduct(10, f"CPU usage {cpu:.0f}% >= threshold {cfg.alert_cpu_percent:.0f}%.")

    ram = host.get("ram_percent")
    if ram is None:
        components["RAM"] = "n/a"
    else:
        components["RAM"] = f"{ram:.0f}%"
        if ram >= cfg.alert_ram_percent:
            deduct(10, f"RAM usage {ram:.0f}% >= threshold {cfg.alert_ram_percent:.0f}%.")

    disk = host.get("disk_percent")
    if disk is None:
        components["Disk"] = "n/a"
    else:
        components["Disk"] = f"{disk:.0f}%"
        if disk >= cfg.alert_disk_percent:
            deduct(15, f"Disk usage {disk:.0f}% >= threshold {cfg.alert_disk_percent:.0f}%.")

    components["GPU"] = "available" if host.get("gpu_available") else "not available"

    # --- Cameras ---
    camera = snapshots.get("camera") or {}
    if not camera.get("db_reachable", True):
        components["Camera"] = COMP_CRITICAL
        deduct(20, f"Camera database unreachable: {camera.get('db_reason') or 'unknown reason'}.")
    else:
        cams = camera.get("cameras", [])
        total = len(cams)
        if total == 0:
            components["Camera"] = "no cameras registered"
        else:
            offline = sum(1 for c in cams if not c.get("is_online_db"))
            fraction = offline / total
            if offline == 0:
                components["Camera"] = OK
            else:
                components["Camera"] = COMP_WARNING if fraction < 1.0 else COMP_CRITICAL
                deduct(round(20 * fraction), f"{offline}/{total} camera(s) offline.")

    # --- AI pipeline latency ---
    pipeline = snapshots.get("ai_pipeline") or {}
    total_ms = pipeline.get("pipeline_total_ms")
    if total_ms is None:
        components["AI Pipeline Latency"] = "n/a"
    else:
        components["AI Pipeline Latency"] = f"{total_ms:.0f}ms"
        if total_ms >= cfg.alert_pipeline_latency_ms:
            deduct(10, f"AI pipeline latency {total_ms:.0f}ms >= threshold {cfg.alert_pipeline_latency_ms:.0f}ms.")

    # --- Evaluation (optional signal; see monitoring/checks/service_checks.py) ---
    evaluation = snapshots.get("evaluation")
    if evaluation is not None:
        if evaluation.get("reachable"):
            components["Evaluation"] = OK
        else:
            components["Evaluation"] = COMP_WARNING
            deduct(5, f"Evaluation reports not accessible: {evaluation.get('reason') or 'unknown reason'} (optional signal).")

    score = max(0, min(100, score))
    core_down = components.get("Backend") == COMP_CRITICAL and components.get("PostgreSQL") == COMP_CRITICAL
    status = _status_for_score(score, core_down)

    if not reasoning:
        reasoning.append("No issues detected across any monitored component.")

    return HealthScoreResult(
        score=score, status=status, components=components, reasoning=reasoning, generated_at=time.time(),
    )
