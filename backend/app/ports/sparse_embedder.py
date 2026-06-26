"""Port: sparse lexical embeddings (fastembed adapter implements this).

Sparse vectors are computed locally (not an LLM call) and live alongside dense
vectors as named vectors in the same Qdrant collection.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import SparseVector


@runtime_checkable
class SparseEmbedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[SparseVector]: ...

    async def embed_query(self, text: str) -> SparseVector: ...
