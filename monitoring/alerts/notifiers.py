"""Alert notification channels.

Log notification is always on (it's just structured logging, subject to
the same rotation/retention as everything else — see
`monitoring/storage/retention.py` and `docs/MONITORING.md`). The webhook
notifier is opt-in (`MONITORING_WEBHOOK_URL`) and posts a small, generic
JSON payload compatible with Slack/Discord-style "incoming webhook"
endpoints as well as any custom receiver.

Neither notifier touches production data or systems — they only ever send
already-computed alert text outward.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("monitoring.alerts")


def log_alert(alert: dict, *, resolved: bool = False) -> None:
    level = logging.INFO if resolved else (logging.CRITICAL if alert.get("severity") == "critical" else logging.WARNING)
    verb = "RESOLVED" if resolved else "ACTIVE"
    logger.log(level, "[%s] %s (%s/%s): %s", verb, alert.get("rule_id"), alert.get("severity"), alert.get("subject"), alert.get("message"))


async def send_webhook(webhook_url: str, alert: dict, *, resolved: bool = False, timeout_seconds: float = 5.0) -> bool:
    if not webhook_url:
        return False
    import httpx

    status_word = "RESOLVED" if resolved else "ALERT"
    payload = {
        "text": f"[VisionMart Monitoring] {status_word} — {alert.get('severity', '').upper()} — {alert.get('rule_id')}: {alert.get('message')}",
        "rule_id": alert.get("rule_id"),
        "severity": alert.get("severity"),
        "subject": alert.get("subject"),
        "message": alert.get("message"),
        "resolved": resolved,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(webhook_url, json=payload)
            return resp.status_code < 400
    except Exception:  # noqa: BLE001 — a failed notification must never crash the monitoring loop
        logger.exception("Failed to deliver alert webhook")
        return False
