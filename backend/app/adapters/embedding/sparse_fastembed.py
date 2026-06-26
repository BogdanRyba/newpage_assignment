"""Sparse embedder adapter — fastembed (implements the SparseEmbedder port).

Sparse vectors are computed locally (BM25 by default — light, offline, no GPU). Routed
through the cassette boundary so replay-mode runs are fully offline (no model download).
CPU work is offloaded to a thread to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio

from app.core.cassette import through_cassette
from app.domain.models import SparseVector

DEFAULT_MODEL = "Qdrant/bm25"


class FastEmbedSparse:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._encoder = None

    def _lazy_encoder(self):  # noqa: ANN202
        if self._encoder is None:
            from fastembed import SparseTextEmbedding

            self._encoder = SparseTextEmbedding(model_name=self.model)
        return self._encoder

    async def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        if not texts:
            return []

        async def produce():  # noqa: ANN202
            def work():  # noqa: ANN202
                embs = list(self._lazy_encoder().embed(texts))
                return [{"indices": e.indices.tolist(), "values": e.values.tolist()} for e in embs]

            return await asyncio.to_thread(work)

        raw = await through_cassette("sparse_documents", self.model, texts, produce)
        return [SparseVector(**r) for r in raw]

    async def embed_query(self, text: str) -> SparseVector:
        async def produce():  # noqa: ANN202
            def work():  # noqa: ANN202
                e = next(iter(self._lazy_encoder().query_embed(text)))
                return {"indices": e.indices.tolist(), "values": e.values.tolist()}

            return await asyncio.to_thread(work)

        raw = await through_cassette("sparse_query", self.model, text, produce)
        return SparseVector(**raw)
