"""Cross-encoder reranker (fastembed) — gated behind RERANK_ENABLED.

Imported lazily so the default (rerank off) path never loads the model. On CPU this is the
slowest stage, which is exactly why it's optional. Sharpens precision of the top_k.
"""

from __future__ import annotations

import asyncio

from app.domain.models import Hit

DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
_encoder = None


def _lazy_encoder():  # noqa: ANN202
    global _encoder
    if _encoder is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        _encoder = TextCrossEncoder(model_name=DEFAULT_MODEL)
    return _encoder


async def rerank(query: str, hits: list[Hit], *, top_k: int) -> list[Hit]:
    if not hits:
        return []

    def work() -> list[float]:
        return list(_lazy_encoder().rerank(query, [h.chunk.text for h in hits]))

    scores = await asyncio.to_thread(work)
    order = sorted(range(len(hits)), key=lambda i: scores[i], reverse=True)
    return [
        Hit(chunk=hits[i].chunk, score=float(scores[i]), source="rerank") for i in order[:top_k]
    ]
