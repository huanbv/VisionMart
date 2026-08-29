"""Shared helper: fetch a Prometheus `/metrics` text endpoint and parse it
into a nested dict keyed by metric name -> label-tuple -> value.

Used by both `camera_health.py` (reads ai-engine's per-camera FPS/dropped-
frame gauges) and `ai_pipeline_health.py` (reads OpenCV/YOLO/ByteTrack
latency histograms) — both endpoints already existed before this
monitoring package was added (`ai-engine/app/main.py`,
`backend/app/api/metrics.py`); this module only ever issues a plain
`GET` against them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetricSample:
    labels: dict[str, str]
    value: float


@dataclass
class ScrapeResult:
    reachable: bool
    reason: str | None
    metrics: dict[str, list[MetricSample]]  # metric_name -> samples

    def gauge(self, name: str, **label_filter: str) -> float | None:
        for s in self.metrics.get(name, []):
            if all(s.labels.get(k) == v for k, v in label_filter.items()):
                return s.value
        return None

    def all_label_values(self, name: str, label: str) -> set[str]:
        return {s.labels[label] for s in self.metrics.get(name, []) if label in s.labels}

    def histogram_stats(self, base_name: str, **label_filter: str) -> dict[str, float] | None:
        """Reconstructs mean/count/sum from a Prometheus histogram's
        `_sum`/`_count` series (the `_bucket` series are not needed for a
        simple mean). Returns None if the histogram has no observations
        yet for the given label filter."""
        count = self.gauge(f"{base_name}_count", **label_filter)
        total = self.gauge(f"{base_name}_sum", **label_filter)
        if count is None or total is None or count == 0:
            return None
        return {"count": count, "sum": total, "mean": total / count}


async def scrape(url: str, timeout_seconds: float = 5.0) -> ScrapeResult:
    import httpx
    from prometheus_client.parser import text_string_to_metric_families

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
    except Exception as exc:  # noqa: BLE001 — any failure means "not reachable", reported honestly below
        return ScrapeResult(reachable=False, reason=str(exc), metrics={})

    metrics: dict[str, list[MetricSample]] = {}
    try:
        for family in text_string_to_metric_families(text):
            for sample in family.samples:
                metrics.setdefault(sample.name, []).append(
                    MetricSample(labels=dict(sample.labels), value=sample.value)
                )
    except Exception as exc:  # noqa: BLE001 — malformed response body
        return ScrapeResult(reachable=False, reason=f"metrics endpoint reachable but unparsable: {exc}", metrics={})

    return ScrapeResult(reachable=True, reason=None, metrics=metrics)


async def check_health(url: str, timeout_seconds: float = 5.0) -> tuple[bool, str | None, float | None]:
    """Returns (ok, reason_if_not_ok, latency_ms)."""
    import time

    import httpx

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.get(url)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}", latency_ms
            return True, None, latency_ms
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), None
