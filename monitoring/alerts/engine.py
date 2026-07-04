"""Alert Engine: evaluates every configured rule against the latest
snapshot, persists active/resolved state to monitoring's own SQLite store
(`monitoring/storage/db.py` — never production Postgres), and dispatches
notifications only for NEWLY activated or newly resolved alerts (not on
every poll an alert stays active, to avoid spamming).
"""

from __future__ import annotations

import logging

from monitoring.alerts.notifiers import log_alert, send_webhook
from monitoring.alerts.rules import AlertRule
from monitoring.storage import db as monitoring_db

logger = logging.getLogger("monitoring.alerts.engine")


class AlertEngine:
    def __init__(self, rules: list[AlertRule], sqlite_path: str, webhook_url: str = "") -> None:
        self.rules = rules
        self.sqlite_path = sqlite_path
        self.webhook_url = webhook_url

    async def evaluate(self, snapshots: dict) -> dict:
        """Runs every rule, updates the alert store, and returns a summary:
        `{"newly_active": [...], "newly_resolved": [...], "still_active": [...]}`.
        """
        newly_active = []
        newly_resolved = []
        still_active = []

        currently_active_before = {
            (a["rule_id"], a["subject"]) for a in monitoring_db.active_alerts(self.sqlite_path)
        }

        triggered_this_poll: set[tuple[str, str]] = set()

        for rule in self.rules:
            try:
                hits = rule.evaluate(snapshots)
            except Exception:  # noqa: BLE001 — a buggy rule must never take down the whole poll
                logger.exception("Alert rule %s raised while evaluating", rule.rule_id)
                continue

            for subject, message in hits:
                key = (rule.rule_id, subject)
                triggered_this_poll.add(key)
                was_active = key in currently_active_before
                monitoring_db.upsert_alert(self.sqlite_path, rule.rule_id, rule.severity, subject, message)
                alert_dict = {"rule_id": rule.rule_id, "severity": rule.severity, "subject": subject, "message": message}
                if was_active:
                    still_active.append(alert_dict)
                else:
                    newly_active.append(alert_dict)
                    log_alert(alert_dict, resolved=False)
                    if self.webhook_url:
                        await send_webhook(self.webhook_url, alert_dict, resolved=False)

        # Anything that was active before but didn't fire this poll has cleared.
        for rule_id, subject in currently_active_before - triggered_this_poll:
            monitoring_db.resolve_alert(self.sqlite_path, rule_id, subject)
            alert_dict = {"rule_id": rule_id, "severity": "info", "subject": subject, "message": "Condition cleared."}
            newly_resolved.append(alert_dict)
            log_alert(alert_dict, resolved=True)
            if self.webhook_url:
                await send_webhook(self.webhook_url, alert_dict, resolved=True)

        return {"newly_active": newly_active, "newly_resolved": newly_resolved, "still_active": still_active}
