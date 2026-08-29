"""Embedding stage — a feature vector per crop, for the SKUs the
classifier was never trained on.

The gap this fills
------------------
A classifier can only answer with a class it was trained on. Stock a new
product and the model does not say "unknown" — it silently assigns the
nearest *old* SKU with high confidence, because softmax always sums to one.
That failure is invisible in the metrics and expensive at the till.

An embedding sidesteps the closed-set assumption: instead of asking "which
of my 40 classes is this", it asks "what does this look like", and the
answer is compared against a gallery of reference vectors. Adding a product
then means adding a handful of reference images — no retraining, no
redeploy. It also makes near-duplicate detection in the training set
possible, which is how you find out a class is 300 photos of the same
bottle from the same angle.

Where the vector comes from
---------------------------
The penultimate layer of the classifier backbone — the representation the
final linear layer consumes. Reusing the classifier's own backbone matters:
it costs *nothing extra* at inference (the forward pass already computed
it), and the features are already tuned to distinguish this shop's
products, unlike a generic ImageNet embedding.

Normalisation
-------------
Vectors are L2-normalised on the way out, which makes cosine similarity a
plain dot product and puts every comparison on the same scale. Without it,
brightness alone changes a vector's magnitude and a well-lit photo of the
wrong product can out-score a dim photo of the right one.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger("ai-engine.vision.embedding")


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    dim: int
    model_version: str


def l2_normalise(vector: list[float]) -> list[float]:
    """Scale to unit length. A zero vector is returned unchanged.

    The zero case is not theoretical — a fully black crop through some
    backbones produces all-zero activations, and dividing by that norm
    would put NaNs into the database, which then poison every later
    similarity query rather than merely being one bad row.
    """
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 1e-12:
        return list(vector)
    return [v / norm for v in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similarity in [-1, 1]. Assumes neither input is normalised."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return float(dot / (na * nb))


def nearest_neighbours(
    query: list[float],
    gallery: list[tuple[str, list[float]]],
    *,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> list[tuple[str, float]]:
    """Rank gallery entries against the query, most similar first.

    Brute force, deliberately. At a few thousand reference vectors this is
    a millisecond of pure Python and needs no extra infrastructure; an ANN
    index would be a dependency and an operational surface for no
    measurable gain at this size. It stops being the right choice somewhere
    around 10^5 vectors — see the pgvector TODO on the ``ai_embeddings``
    model, which is the intended upgrade path.
    """
    scored = [(label, cosine_similarity(query, vec)) for label, vec in gallery]
    scored = [(l, s) for l, s in scored if s >= min_similarity]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def decide_by_embedding(
    query: list[float],
    gallery: list[tuple[str, list[float]]],
    *,
    min_similarity: float = 0.75,
    min_margin: float = 0.05,
) -> tuple[str | None, float, str]:
    """Turn neighbours into a decision, or an honest refusal.

    Two gates, and both matter:

    * ``min_similarity`` — the best match must actually be close. Without
      it, a completely unknown product still returns *some* nearest
      neighbour and would be confidently mislabelled, which is the exact
      failure embeddings were added to prevent.
    * ``min_margin`` — the best must beat the runner-up by a clear gap.
      Two sizes of the same drink sit very close together in feature space;
      when the top two are within noise of each other, refusing is correct
      and OCR is the stage that can actually tell them apart.

    Returns ``(sku, similarity, reason)``; ``sku`` is ``None`` when either
    gate rejects, with the reason recorded for the dashboard.
    """
    ranked = nearest_neighbours(query, gallery, top_k=2)
    if not ranked:
        return None, 0.0, "gallery rỗng"

    best_sku, best_score = ranked[0]
    if best_score < min_similarity:
        return None, best_score, (
            f"gần nhất {best_sku} chỉ đạt {best_score:.3f} < ngưỡng "
            f"{min_similarity:.2f} — có thể là sản phẩm chưa có trong bộ mẫu"
        )
    if len(ranked) > 1:
        margin = best_score - ranked[1][1]
        if margin < min_margin:
            return None, best_score, (
                f"{best_sku} ({best_score:.3f}) và {ranked[1][0]} "
                f"({ranked[1][1]:.3f}) quá sát nhau (biên {margin:.3f}) — cần OCR"
            )
    return best_sku, best_score, f"khớp {best_sku} độ tương đồng {best_score:.3f}"


def extract_from_classifier(classification) -> EmbeddingResult | None:
    """Wrap the embedding the classifier already produced.

    A separate forward pass is *not* run here. ``ClassificationResult``
    already carries the penultimate-layer activations when the classifier
    was asked for them, and re-running the backbone to get a vector it
    just computed would double the cost of the most expensive stage that
    routinely runs.
    """
    if classification is None:
        return None
    vector = getattr(classification, "embedding", None)
    if not vector:
        return None
    try:
        normalised = l2_normalise([float(v) for v in vector])
    except (TypeError, ValueError):
        logger.warning("embedding: non-numeric vector from classifier, skipped")
        return None
    return EmbeddingResult(
        vector=normalised,
        dim=len(normalised),
        model_version=getattr(classification, "model_version", "unknown"),
    )
