"""Reciprocal Rank Fusion.

Merges the dense and sparse ranked lists without having to reconcile their score scales:
each list contributes 1/(k+rank) to a chunk's fused score. k dampens the contribution of
low ranks. Deterministic and order-stable for ties.
"""

from __future__ import annotations

from app.domain.models import Hit


def reciprocal_rank_fusion(rankings: list[list[Hit]], k: int = 60) -> list[Hit]:
    scores: dict[str, float] = {}
    seen: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            key = hit.chunk.point_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            # keep the first-seen Hit object for its chunk/payload
            seen.setdefault(key, hit)

    fused = [
        Hit(chunk=seen[key].chunk, score=score, source="fused") for key, score in scores.items()
    ]
    fused.sort(key=lambda h: h.score, reverse=True)
    return fused
