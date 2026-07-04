"""Production Readiness Report -- Part 5 of the Final Production Readiness
spec. Runs the same `visionmart.checks.run_all_checks` engine the
`doctor` CLI uses (Part 6), and packages the results as a single report
consumed by `monitoring/server.py`'s `GET /api/readiness` (proxied by the
backend at `/ops-monitoring/readiness`, displayed on the System Health
dashboard).

Kept intentionally thin: all the actual checking logic lives in
`visionmart/checks.py` so there is exactly one implementation of "is
Postgres reachable" (etc.), not two -- this module only aggregates and
labels.
"""

from __future__ import annotations

import time

from visionmart.checks import FAIL, WARNING, CheckResult, run_all_checks
from visionmart.config import DoctorConfig


def _overall_status(results: list[CheckResult]) -> str:
    if any(r.status == FAIL for r in results):
        return FAIL
    if any(r.status == WARNING for r in results):
        return WARNING
    return "PASS"


async def build_readiness_report(cfg: DoctorConfig | None = None) -> dict:
    cfg = cfg or DoctorConfig()
    results = await run_all_checks(cfg)

    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r.to_dict())

    counts = {"PASS": 0, "WARNING": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    return {
        "generated_at": time.time(),
        "overall_status": _overall_status(results),
        "counts": counts,
        "categories": by_category,
        "checks": [r.to_dict() for r in results],
    }
