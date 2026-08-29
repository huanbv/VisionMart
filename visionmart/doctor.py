"""`visionmart doctor` -- Part 6, Deployment Validation.

Runs every check in `visionmart.checks`, prints a PASS/WARNING/FAIL table
grouped by category, and exits non-zero if any check FAILed (a WARNING
alone does not fail the exit code -- per the spec, only "critical checks"
failing should stop a deploy script that chains on this command).

Never mutates anything -- see the module docstrings on `visionmart.checks`
and `docs/45_DEPLOYMENT_VALIDATION.md` for the read-only audit.
"""

from __future__ import annotations

import asyncio
import sys

from visionmart.checks import FAIL, PASS, WARNING, CheckResult, run_all_checks
from visionmart.config import DoctorConfig

_STATUS_ORDER = {FAIL: 0, WARNING: 1, PASS: 2}


def _format_report(results: list[CheckResult]) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("VisionMart Deployment Doctor")
    lines.append("=" * 78)

    by_category: dict[str, list[CheckResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    counts = {PASS: 0, WARNING: 0, FAIL: 0}
    for r in results:
        counts[r.status] += 1

    for category in sorted(by_category):
        lines.append("")
        lines.append(f"-- {category} " + "-" * max(0, 74 - len(category)))
        for r in sorted(by_category[category], key=lambda x: _STATUS_ORDER[x.status]):
            lines.append(f"  [{r.status:7s}] {r.name}")
            lines.append(f"            {r.detail}")
            if r.recommendation and r.status != PASS:
                lines.append(f"            -> {r.recommendation}")

    lines.append("")
    lines.append("=" * 78)
    lines.append(f"Summary: {counts[PASS]} PASS, {counts[WARNING]} WARNING, {counts[FAIL]} FAIL (of {len(results)} checks)")
    if counts[FAIL] > 0:
        lines.append("Result: FAIL -- one or more critical checks failed. Review the items above before deploying.")
    elif counts[WARNING] > 0:
        lines.append("Result: PASS WITH WARNINGS -- deployable, but review the warnings above.")
    else:
        lines.append("Result: PASS -- all checks passed.")
    lines.append("=" * 78)
    return "\n".join(lines)


async def _run() -> int:
    cfg = DoctorConfig()
    results = await run_all_checks(cfg)
    print(_format_report(results))
    return 1 if any(r.status == FAIL for r in results) else 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
