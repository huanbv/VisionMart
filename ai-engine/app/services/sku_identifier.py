"""Orchestrates the second model stage: crop -> classify -> match.

Sits between `person_tracker` (which produces boxes) and the cart logic
(which needs SKUs). Keeping it in its own module means `frame.py` gains a
few lines rather than a second pipeline inlined into an already long
endpoint.

The per-track cache is the reason this is affordable on CPU
-----------------------------------------------------------
A tracked object persists for dozens of frames. Classifying it on every
one of them would multiply the classifier cost by the frame rate for no
new information — the object's identity does not change while ByteTrack
holds the same id. So a track is classified once, and re-classified only
when:

* the cached answer was *not* confident (worth another look from a new
  angle — the shopper may have rotated the label toward the camera), or
* the cache entry has aged out (guards against a recycled track id
  silently inheriting the previous object's SKU).

With the cache, added cost is roughly one classifier call per new track
instead of one per detection per frame.

Disabled by default: with `ENABLE_SKU_CLASSIFIER` off this module is never
called, and `frame.py` keeps using the class-map path exactly as before.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.services.product_mapper import list_known_brands
from app.vision.classify import get_classifier
from app.vision.crop import CropResult, crop_detections
from app.vision.embedding.extractor import extract_from_classifier
from app.vision.matching import MatchResult, match_product
from app.vision.ocr.reader import get_reader, should_run_ocr

logger = logging.getLogger("ai-engine.sku_identifier")

# track_key -> (MatchResult, monotonic_ts)
_TRACK_CACHE: dict[str, tuple[MatchResult, float]] = {}
_CACHE_TTL_SECONDS = 30.0
# Bounded so a long-running process with churning track ids can't grow it
# without limit.
_CACHE_MAX_ENTRIES = 2000


@dataclass(frozen=True)
class IdentifiedObject:
    """One detection with its resolved SKU and per-stage confidences.

    The per-stage results (``classification``, ``ocr``, ``embedding``) are
    carried alongside the final ``match`` rather than folded into it,
    because the dashboard's whole purpose is showing *how* the answer was
    reached — a single resolved SKU cannot explain itself. They are all
    ``None`` when the corresponding stage is disabled, which is the default.
    """

    detection: Any                 # TrackedObject
    match: MatchResult
    crop: CropResult | None
    from_cache: bool
    classification: Any = None
    ocr: Any = None
    embedding: Any = None


def _track_key(camera_key: str, track_id: Any) -> str:
    return f"{camera_key}:{track_id}"


def _prune_cache(now: float) -> None:
    if len(_TRACK_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    stale = [k for k, (_, ts) in _TRACK_CACHE.items() if now - ts > _CACHE_TTL_SECONDS]
    for key in stale:
        _TRACK_CACHE.pop(key, None)
    if len(_TRACK_CACHE) > _CACHE_MAX_ENTRIES:
        # Still oversized: drop the oldest entries outright rather than
        # letting memory grow unbounded.
        for key, _ in sorted(_TRACK_CACHE.items(), key=lambda kv: kv[1][1])[:500]:
            _TRACK_CACHE.pop(key, None)


def reset_cache() -> None:
    """Clear cached identities — call after deploying a new classifier."""
    _TRACK_CACHE.clear()


def identify(
    frame_bgr: np.ndarray,
    detections: list[Any],
    *,
    camera_key: str,
    organization_id: str,
    branch_id: str,
    cfg: Any,
) -> list[IdentifiedObject]:
    """Resolve SKUs for every product-like detection in this frame."""
    now = time.monotonic()
    _prune_cache(now)

    classifier = get_classifier()
    min_conf = getattr(cfg, "classifier_min_confidence", 0.55)

    # 1) Reuse confident cached identities; collect the rest for the model.
    pending: list[Any] = []
    results: list[IdentifiedObject] = []
    for det in detections:
        if str(getattr(det, "class_name", "")).lower() == "person":
            continue
        key = _track_key(camera_key, getattr(det, "track_id", None))
        cached = _TRACK_CACHE.get(key)
        if cached is not None:
            match, ts = cached
            fresh = now - ts <= _CACHE_TTL_SECONDS
            # Only trust the cache when the earlier answer was solid;
            # a weak one gets another chance from this new viewpoint.
            if fresh and match.final_confidence >= min_conf:
                results.append(
                    IdentifiedObject(detection=det, match=match, crop=None, from_cache=True)
                )
                continue
        pending.append(det)

    if not pending:
        return results

    # 2) Crop everything still pending, then classify in one batch.
    crops = crop_detections(
        frame_bgr,
        pending,
        padding=getattr(cfg, "crop_padding", 0.08),
        min_size=getattr(cfg, "crop_min_size", 24),
    )
    crop_by_track = {c.track_id: c for c in crops}

    classifications: dict[Any, Any] = {}
    if classifier is not None and crops:
        try:
            batch = classifier.classify_batch([c.image for c in crops])
            for crop, result in zip(crops, batch):
                if result is not None:
                    classifications[crop.track_id] = result
        except Exception:
            # Classification is an enhancement; never let it fail the frame.
            logger.exception("SKU classification batch failed")

    # 3) Decide a SKU per detection and cache the outcome.
    # 2b) OCR only where the classifier could not settle. Budgeted per
    # frame: OCR is the one stage that can blow the frame time outright,
    # so a crowded shelf where 20 objects are all uncertain must not turn
    # into a two-second frame. The budget is spent on the *least* confident
    # detections first, because that is where reading the label pays most.
    ocr_results: dict[Any, Any] = {}
    if getattr(cfg, "enable_ocr_fallback", False) and crops:
        candidates = [
            c for c in crops
            if should_run_ocr(classifications.get(c.track_id), cfg)
        ]
        candidates.sort(
            key=lambda c: getattr(classifications.get(c.track_id), "confidence", 0.0)
        )
        budget = int(getattr(cfg, "ocr_max_per_frame", 3))
        if candidates[budget:]:
            logger.debug(
                "OCR budget %d reached; %d uncertain crops skipped this frame",
                budget, len(candidates) - budget,
            )
        reader = get_reader(cfg)
        brands = list_known_brands(organization_id)
        for crop in candidates[:budget]:
            try:
                out = reader.read(crop.image, brands)
            except Exception:
                logger.exception("OCR failed for track %s", crop.track_id)
                continue
            if out is not None and out.has_signal:
                ocr_results[crop.track_id] = out

    # 3) Decide a SKU per detection and cache the outcome.
    for det in pending:
        track_id = getattr(det, "track_id", None)
        classification = classifications.get(track_id)
        ocr = ocr_results.get(track_id)
        match = match_product(
            organization_id=organization_id,
            branch_id=branch_id,
            class_name=str(getattr(det, "class_name", "")),
            yolo_confidence=float(getattr(det, "confidence", 0.0) or 0.0),
            classification=classification,
            classifier_min_confidence=min_conf,
            ocr=ocr,
        )
        if track_id is not None:
            _TRACK_CACHE[_track_key(camera_key, track_id)] = (match, now)
        results.append(
            IdentifiedObject(
                detection=det,
                match=match,
                crop=crop_by_track.get(track_id),
                from_cache=False,
                classification=classification,
                ocr=ocr,
                embedding=(
                    extract_from_classifier(classification)
                    if getattr(cfg, "enable_embeddings", False)
                    else None
                ),
            )
        )
    return results
