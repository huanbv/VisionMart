"""Optional "is the Evaluation Framework producing reports" signal.

Deliberately the lightest-weight check in `monitoring/collectors/` — it
never imports `evaluation.*` (the Evaluation Framework's own dependency
set, e.g. matplotlib/openpyxl, is intentionally not a runtime dependency
of the monitoring service) and never runs an evaluation. It only checks,
via the filesystem, whether the configured reports directory exists and
has produced anything recently. Used by:

  - `monitoring/health_score.py` (the "Evaluation" component — optional,
    never penalizes heavily since it isn't a production-critical path).
  - `monitoring/readiness.py` and `monitoring/doctor.py` (the
    "Evaluation" readiness-checklist category).

Requires the monitoring container to have the repo mounted read-only
(`.:/app/repo:ro` in docker-compose.yml) — if that mount isn't present,
this reports `reachable=False` with a clear reason rather than raising.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvaluationStatus:
    reachable: bool
    reason: str | None
    reports_dir: str
    report_count: int
    last_report_age_seconds: float | None

    def to_dict(self) -> dict:
        return {
            "reachable": self.reachable,
            "reason": self.reason,
            "reports_dir": self.reports_dir,
            "report_count": self.report_count,
            "last_report_age_seconds": self.last_report_age_seconds,
        }


_REPORT_GLOBS = ("evaluation_*.json", "*_report_*.md", "evaluation_*.xlsx")


def check_evaluation_reports(reports_dir: str) -> EvaluationStatus:
    path = Path(reports_dir)
    if not path.exists():
        return EvaluationStatus(
            reachable=False,
            reason=f"Reports directory not found: {path} (no `evaluate` run has produced output yet, "
                    f"or MONITORING_EVALUATION_REPORTS_DIR / repo mount is misconfigured).",
            reports_dir=str(path), report_count=0, last_report_age_seconds=None,
        )

    try:
        report_files = []
        for pattern in _REPORT_GLOBS:
            report_files.extend(path.glob(pattern))
    except OSError as exc:
        return EvaluationStatus(
            reachable=False, reason=f"Could not list reports directory: {exc}",
            reports_dir=str(path), report_count=0, last_report_age_seconds=None,
        )

    if not report_files:
        return EvaluationStatus(
            reachable=True,
            reason="Directory exists but no evaluation report files found yet.",
            reports_dir=str(path), report_count=0, last_report_age_seconds=None,
        )

    newest = max(f.stat().st_mtime for f in report_files)
    return EvaluationStatus(
        reachable=True, reason=None, reports_dir=str(path),
        report_count=len(report_files), last_report_age_seconds=round(time.time() - newest, 1),
    )
