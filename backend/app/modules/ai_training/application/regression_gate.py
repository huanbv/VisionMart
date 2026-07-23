"""Regression gate for model deployment.

Retraining does not always improve a model. More data can hurt when the
new labels are noisy, unbalanced, or drawn from a narrow slice of
conditions — and because a worse detector still *runs*, the damage shows
up as a slow drift in business metrics rather than an error anyone sees.

This gate makes that failure loud: before a new weight goes live, its
metrics are compared against the currently deployed weight's, and a
meaningful drop blocks the deploy.

It is deliberately a *guard rail*, not a lock — an operator can override
with an explicit force flag, because there are legitimate reasons to
accept a small metric drop (e.g. trading recall for precision after a
false-positive complaint). What the gate prevents is doing so *without
noticing*.

Metric selection is by priority, not a single hard-coded key, because
ultralytics' ``results_dict`` key names vary across versions
(``metrics/mAP50-95(B)``, ``metrics/mAP50-95``, …).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Ordered best-first: mAP50-95 is the strictest summary of detection
# quality, so prefer it when present and fall back down the list.
_METRIC_PRIORITY: tuple[str, ...] = (
    "map50-95",
    "map_50_95",
    "map5095",
    "map50",
    "map_50",
    "fitness",
)

# A metric may wobble slightly between runs on identical data; blocking on
# noise would train operators to always pass --force, which defeats the
# gate. Only a drop bigger than this counts as a regression.
DEFAULT_TOLERANCE = 0.01


@dataclass
class GateResult:
    allowed: bool
    reason: str
    metric_name: str | None = None
    candidate_value: float | None = None
    baseline_value: float | None = None
    delta: float | None = None
    comparable: bool = False
    details: dict[str, float] = field(default_factory=dict)


def _normalise(key: str) -> str:
    """``metrics/mAP50-95(B)`` -> ``map50-95``."""
    out = key.lower()
    if "/" in out:
        out = out.rsplit("/", 1)[-1]
    return out.replace("(b)", "").replace("(m)", "").strip()


def pick_metric(metrics: dict | None) -> tuple[str | None, float | None]:
    """Highest-priority comparable metric present in ``metrics``."""
    if not metrics:
        return None, None
    normalised: dict[str, tuple[str, float]] = {}
    for raw_key, value in metrics.items():
        if not isinstance(value, (int, float)):
            continue
        normalised.setdefault(_normalise(str(raw_key)), (str(raw_key), float(value)))
    for wanted in _METRIC_PRIORITY:
        if wanted in normalised:
            raw_key, value = normalised[wanted]
            return raw_key, value
    return None, None


def evaluate(
    *,
    candidate_metrics: dict | None,
    baseline_metrics: dict | None,
    tolerance: float = DEFAULT_TOLERANCE,
    force: bool = False,
) -> GateResult:
    """Decide whether a candidate weight may be deployed.

    Deploy is allowed when there is nothing to compare against (first
    deploy, or metrics missing) — blocking then would make the very first
    model undeployable. Those cases are reported as ``comparable=False``
    so the UI can say "not verified" rather than implying the model passed
    a check that never ran.
    """
    cand_key, cand_value = pick_metric(candidate_metrics)
    base_key, base_value = pick_metric(baseline_metrics)

    if force:
        return GateResult(
            allowed=True,
            reason="Regression gate overridden by operator.",
            metric_name=cand_key,
            candidate_value=cand_value,
            baseline_value=base_value,
            delta=(
                cand_value - base_value
                if cand_value is not None and base_value is not None
                else None
            ),
            comparable=cand_value is not None and base_value is not None,
        )

    if base_value is None:
        return GateResult(
            allowed=True,
            reason="No previously deployed model to compare against — deploy allowed, quality not verified.",
            metric_name=cand_key,
            candidate_value=cand_value,
            comparable=False,
        )
    if cand_value is None:
        return GateResult(
            allowed=True,
            reason="Candidate has no comparable metrics — deploy allowed, quality not verified.",
            baseline_value=base_value,
            metric_name=base_key,
            comparable=False,
        )
    if _normalise(cand_key or "") != _normalise(base_key or ""):
        # Comparing mAP50 against fitness would be meaningless.
        return GateResult(
            allowed=True,
            reason=(
                f"Metrics are not comparable ({cand_key} vs {base_key}) — "
                "deploy allowed, quality not verified."
            ),
            metric_name=cand_key,
            candidate_value=cand_value,
            baseline_value=base_value,
            comparable=False,
        )

    delta = cand_value - base_value
    if delta < -abs(tolerance):
        return GateResult(
            allowed=False,
            reason=(
                f"Blocked: {cand_key} dropped from {base_value:.4f} to "
                f"{cand_value:.4f} ({delta:+.4f}), beyond the {tolerance:.4f} "
                "tolerance. Deploy anyway with force=true if this trade-off is intended."
            ),
            metric_name=cand_key,
            candidate_value=cand_value,
            baseline_value=base_value,
            delta=delta,
            comparable=True,
        )

    verdict = "improved" if delta > 0 else "held steady"
    return GateResult(
        allowed=True,
        reason=f"{cand_key} {verdict}: {base_value:.4f} -> {cand_value:.4f} ({delta:+.4f}).",
        metric_name=cand_key,
        candidate_value=cand_value,
        baseline_value=base_value,
        delta=delta,
        comparable=True,
    )
