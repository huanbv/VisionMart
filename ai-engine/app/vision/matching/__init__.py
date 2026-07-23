"""Product matching — combines per-stage confidences into a SKU decision."""

from app.vision.matching.matcher import MatchResult, combine_confidence, match_product

__all__ = ["MatchResult", "combine_confidence", "match_product"]
