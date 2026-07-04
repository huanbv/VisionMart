"""Monitoring's own SQLite store.

Deliberately a SEPARATE database file from production Postgres — nothing
in this module ever opens a connection to `DATABASE_URL` with write
intent; production data is only ever read (see `monitoring/audit/` and
`monitoring/collectors/`) and everything written here lands in this
file only. Safe to delete at any time: it holds derived/observational
history, not source-of-truth business data.

Schema
------
resource_snapshots        Time series of every collector's output (camera /
                           ai_pipeline / system_resources), used for
                           history, charts, and uptime/uptime-adjacent
                           derivations.
camera_state_events        Recorded only on an online<->offline transition,
                           so `reconnect_count` can be derived as
                           "count of offline->online transitions observed
                           since this service started" (see module
                           docstring in `collectors/camera_health.py` for
                           why a true historical count isn't otherwise
                           obtainable).
alerts                      Alert Engine output — one row per rule
                           activation, with first_seen/last_seen/resolved_at
                           for de-duplication (§ alerts/engine.py).
session_lifecycle_events   Append-only, one row whenever a shopping
                           session's derived lifecycle stage changes
                           between two polls (§ audit/session_lifecycle.py).
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS resource_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    category TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_category_ts ON resource_snapshots(category, ts);

CREATE TABLE IF NOT EXISTS camera_state_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    camera_id TEXT NOT NULL,
    camera_code TEXT,
    is_online INTEGER NOT NULL,
    transition TEXT NOT NULL  -- 'online' | 'offline'
);
CREATE INDEX IF NOT EXISTS idx_camera_events_camera_ts ON camera_state_events(camera_id, ts);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    resolved_at REAL,
    status TEXT NOT NULL  -- 'active' | 'resolved'
);
CREATE INDEX IF NOT EXISTS idx_alerts_rule_subject ON alerts(rule_id, subject);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

CREATE TABLE IF NOT EXISTS session_lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    cart_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_session_events_cart_ts ON session_lifecycle_events(cart_id, ts);
"""


def init_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect(path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def insert_snapshot(path: str, category: str, payload: dict[str, Any], ts: float | None = None) -> None:
    ts = ts if ts is not None else time.time()
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO resource_snapshots (ts, category, payload_json) VALUES (?, ?, ?)",
            (ts, category, json.dumps(payload, default=str)),
        )
        conn.commit()


def latest_snapshot(path: str, category: str) -> dict[str, Any] | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT ts, payload_json FROM resource_snapshots WHERE category = ? ORDER BY ts DESC LIMIT 1",
            (category,),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    payload["_snapshot_ts"] = row["ts"]
    return payload


def snapshot_history(path: str, category: str, since_ts: float, limit: int = 500) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT ts, payload_json FROM resource_snapshots WHERE category = ? AND ts >= ? ORDER BY ts ASC LIMIT ?",
            (category, since_ts, limit),
        ).fetchall()
    out = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        payload["_snapshot_ts"] = row["ts"]
        out.append(payload)
    return out


def record_camera_transition(path: str, camera_id: str, camera_code: str | None, is_online: bool, ts: float | None = None) -> None:
    ts = ts if ts is not None else time.time()
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO camera_state_events (ts, camera_id, camera_code, is_online, transition) VALUES (?, ?, ?, ?, ?)",
            (ts, camera_id, camera_code, int(is_online), "online" if is_online else "offline"),
        )
        conn.commit()


def reconnect_count(path: str, camera_id: str, since_ts: float = 0.0) -> int:
    """Number of offline->online transitions observed since `since_ts`
    (default: since this monitoring database was created). This is NOT a
    lifetime/historical count — see `collectors/camera_health.py` for why
    that isn't reconstructable."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM camera_state_events WHERE camera_id = ? AND transition = 'online' AND ts >= ?",
            (camera_id, since_ts),
        ).fetchone()
    return int(row["n"]) if row else 0


def last_camera_state(path: str, camera_id: str) -> bool | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT is_online FROM camera_state_events WHERE camera_id = ? ORDER BY ts DESC LIMIT 1",
            (camera_id,),
        ).fetchone()
    return bool(row["is_online"]) if row is not None else None


def upsert_alert(path: str, rule_id: str, severity: str, subject: str, message: str, ts: float | None = None) -> None:
    """Activates or refreshes an alert. If an active alert with the same
    (rule_id, subject) exists, just bump last_seen/message; otherwise
    insert a new active alert row."""
    ts = ts if ts is not None else time.time()
    with connect(path) as conn:
        row = conn.execute(
            "SELECT id FROM alerts WHERE rule_id = ? AND subject = ? AND status = 'active'",
            (rule_id, subject),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE alerts SET last_seen = ?, message = ?, severity = ? WHERE id = ?",
                (ts, message, severity, row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO alerts (rule_id, severity, subject, message, first_seen, last_seen, resolved_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, 'active')",
                (rule_id, severity, subject, message, ts, ts),
            )
        conn.commit()


def resolve_alert(path: str, rule_id: str, subject: str, ts: float | None = None) -> None:
    ts = ts if ts is not None else time.time()
    with connect(path) as conn:
        conn.execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = ? WHERE rule_id = ? AND subject = ? AND status = 'active'",
            (ts, rule_id, subject),
        )
        conn.commit()


def active_alerts(path: str) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE status = 'active' ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def recent_alerts(path: str, limit: int = 100) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY last_seen DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def record_session_stage(path: str, cart_id: str, stage: str, detail: dict[str, Any] | None, ts: float | None = None) -> None:
    ts = ts if ts is not None else time.time()
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO session_lifecycle_events (ts, cart_id, stage, detail_json) VALUES (?, ?, ?, ?)",
            (ts, cart_id, stage, json.dumps(detail, default=str) if detail else None),
        )
        conn.commit()


def last_session_stage(path: str, cart_id: str) -> str | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT stage FROM session_lifecycle_events WHERE cart_id = ? ORDER BY ts DESC LIMIT 1",
            (cart_id,),
        ).fetchone()
    return row["stage"] if row is not None else None


def session_events(path: str, cart_id: str) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT ts, stage, detail_json FROM session_lifecycle_events WHERE cart_id = ? ORDER BY ts ASC",
            (cart_id,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "ts": r["ts"], "stage": r["stage"],
            "detail": json.loads(r["detail_json"]) if r["detail_json"] else None,
        })
    return out


def purge_older_than(path: str, retention_days: int) -> dict[str, int]:
    """Deletes rows older than `retention_days` from every table in this
    (monitoring-owned) database. Never touches production Postgres."""
    cutoff = time.time() - retention_days * 86400
    deleted = {}
    with connect(path) as conn:
        for table, col in (
            ("resource_snapshots", "ts"),
            ("camera_state_events", "ts"),
            ("session_lifecycle_events", "ts"),
        ):
            cur = conn.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
            deleted[table] = cur.rowcount
        # Resolved alerts older than the retention window are pruned too;
        # active alerts are kept regardless of age (they're still relevant).
        cur = conn.execute(
            "DELETE FROM alerts WHERE status = 'resolved' AND resolved_at IS NOT NULL AND resolved_at < ?",
            (cutoff,),
        )
        deleted["alerts"] = cur.rowcount
        conn.commit()
        conn.execute("VACUUM;")
    return deleted
