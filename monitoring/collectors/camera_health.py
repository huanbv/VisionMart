"""Camera connectivity monitoring.

Data sources, all read-only:

  - `cameras` table (raw SQL `SELECT`, no ORM import) for `is_online`,
    `last_seen_at`, `name`, `code` — the same columns the backend itself
    already maintains via camera heartbeats (see
    `backend/app/modules/camera/application/services.py`). Nothing here
    writes to this table.
  - ai-engine's existing `/metrics` Prometheus endpoint for per-camera FPS
    (`ai_engine_vision_camera_fps`), dropped frames
    (`ai_engine_vision_dropped_frames_total`), and pipeline latency
    (`ai_engine_vision_pipeline_total_seconds`) — labelled by
    `camera_key`, which ai-engine sets to `str(camera_id)` (see
    `ai-engine/app/api/frame.py::_track_key` / the `camera_key` assignment
    in the same file), so it lines up directly with `cameras.id`.

Honesty notes (read before trusting a number):

  - These FPS/dropped-frame/latency metrics are ONLY populated when
    `ENABLE_PERFORMANCE_METRICS=true` on ai-engine (see
    `ai-engine/app/vision/pipeline.py::record_pipeline_timing`) — a flag
    that defaults to `false`. If it's off, this collector reports
    `fps=None`/`dropped_frames=None`/`latency_ms=None` with a `reason`,
    not zero.
  - `reconnect_count` is derived by THIS service observing online<->offline
    transitions over time (via `monitoring/storage/db.py`), starting from
    whenever monitoring was first deployed. There is no historical
    online/offline event log anywhere in the existing schema (confirmed
    while building `evaluation/cart/cart_metrics.py`'s `camera_uptime`
    field — same finding applies here), so a reconnect count from BEFORE
    monitoring started cannot be recovered. This is disclosed per-camera
    via `reconnect_count_since`.
  - "Frozen frame" detection (two frames intentionally near-duplicate,
    an ai symptom of a stalled encoder) requires decoding and diffing
    consecutive frames — the production pipeline does not expose this via
    Prometheus, and adding it would mean modifying `ai-engine/app/vision/`,
    which is out of scope for this monitoring layer (see
    `evaluation/metrics/camera_quality_metrics.py` for the offline
    equivalent, usable during dedicated evaluation runs). This collector
    reports `frozen_frame_detection_available=False` rather than
    fabricating a value.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from monitoring.collectors.http_metrics import ScrapeResult, scrape
from monitoring.storage import db as monitoring_db


@dataclass
class CameraStatus:
    camera_id: str
    code: str
    name: str
    is_online_db: bool
    last_seen_at: str | None
    seconds_since_last_seen: float | None
    reconnect_count_since_monitoring_start: int
    fps: float | None
    dropped_frames_total: float | None
    avg_pipeline_latency_ms: float | None
    fps_reason: str | None
    frozen_frame_detection_available: bool = False


@dataclass
class CameraHealthSnapshot:
    checked_at: float
    ai_engine_reachable: bool
    ai_engine_reason: str | None
    performance_metrics_enabled_hint: bool  # best-effort: True if ANY camera_key had FPS data
    cameras: list[CameraStatus] = field(default_factory=list)
    db_reachable: bool = True
    db_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "ai_engine_reachable": self.ai_engine_reachable,
            "ai_engine_reason": self.ai_engine_reason,
            "performance_metrics_enabled_hint": self.performance_metrics_enabled_hint,
            "cameras": [vars(c) for c in self.cameras],
            "db_reachable": self.db_reachable,
            "db_reason": self.db_reason,
        }


async def _fetch_cameras_from_db(database_url: str, organization_id: str | None) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    try:
        query = (
            "SELECT id, code, name, is_online, last_seen_at, organization_id "
            "FROM cameras WHERE is_deleted = false"
        )
        params: dict = {}
        if organization_id:
            query += " AND organization_id = :org_id"
            params["org_id"] = organization_id
        async with engine.connect() as conn:
            result = await conn.execute(text(query), params)
            rows = [dict(r._mapping) for r in result]
        return rows
    finally:
        await engine.dispose()


def _camera_metric(scrape_result: ScrapeResult, camera_key: str) -> tuple[float | None, float | None, float | None]:
    fps = scrape_result.gauge("ai_engine_vision_camera_fps", camera_key=camera_key)
    dropped = scrape_result.gauge("ai_engine_vision_dropped_frames_total", camera_key=camera_key)
    stats = scrape_result.histogram_stats("ai_engine_vision_pipeline_total_seconds", camera_key=camera_key)
    latency_ms = stats["mean"] * 1000.0 if stats else None
    return fps, dropped, latency_ms


async def collect_camera_health(
    database_url: str,
    ai_engine_url: str,
    sqlite_path: str,
    *,
    organization_id: str | None = None,
) -> CameraHealthSnapshot:
    now = time.time()
    try:
        cameras = await _fetch_cameras_from_db(database_url, organization_id)
        db_reachable, db_reason = True, None
    except Exception as exc:  # noqa: BLE001 — DB being down must not take the whole poll cycle down with it
        cameras, db_reachable, db_reason = [], False, str(exc)

    scrape_result = await scrape(f"{ai_engine_url}/metrics")

    any_fps_data = bool(scrape_result.metrics.get("ai_engine_vision_camera_fps"))

    statuses: list[CameraStatus] = []
    for row in cameras:
        camera_id = str(row["id"])
        is_online = bool(row["is_online"])
        last_seen = row["last_seen_at"]
        seconds_since = None
        if last_seen is not None:
            try:
                import datetime

                last_seen_dt = last_seen if isinstance(last_seen, datetime.datetime) else datetime.datetime.fromisoformat(str(last_seen))
                if last_seen_dt.tzinfo is None:
                    last_seen_dt = last_seen_dt.replace(tzinfo=datetime.timezone.utc)
                seconds_since = (datetime.datetime.now(datetime.timezone.utc) - last_seen_dt).total_seconds()
            except Exception:
                seconds_since = None

        prev_state = monitoring_db.last_camera_state(sqlite_path, camera_id)
        if prev_state is None or prev_state != is_online:
            monitoring_db.record_camera_transition(sqlite_path, camera_id, str(row["code"]), is_online, ts=now)

        reconnects = monitoring_db.reconnect_count(sqlite_path, camera_id)

        fps, dropped, latency_ms = (None, None, None)
        fps_reason = "ai-engine /metrics not reachable" if not scrape_result.reachable else None
        if scrape_result.reachable:
            fps, dropped, latency_ms = _camera_metric(scrape_result, camera_id)
            if fps is None and dropped is None and latency_ms is None:
                fps_reason = (
                    "No performance-metrics samples for this camera yet — either "
                    "ENABLE_PERFORMANCE_METRICS=false on ai-engine, or this camera has not "
                    "processed a frame since ai-engine last restarted."
                )

        statuses.append(
            CameraStatus(
                camera_id=camera_id,
                code=str(row["code"]),
                name=str(row["name"]),
                is_online_db=is_online,
                last_seen_at=str(last_seen) if last_seen is not None else None,
                seconds_since_last_seen=seconds_since,
                reconnect_count_since_monitoring_start=reconnects,
                fps=fps,
                dropped_frames_total=dropped,
                avg_pipeline_latency_ms=latency_ms,
                fps_reason=fps_reason,
            )
        )

    return CameraHealthSnapshot(
        checked_at=now,
        ai_engine_reachable=scrape_result.reachable,
        ai_engine_reason=scrape_result.reason,
        performance_metrics_enabled_hint=any_fps_data,
        cameras=statuses,
        db_reachable=db_reachable,
        db_reason=db_reason,
    )
