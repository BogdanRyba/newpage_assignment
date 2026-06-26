"""Port: dense embeddings (LangChain/Gemini adapter implements this).

Volatile IO boundary — the model/provider is swappable (Gemini ↔ Voyage ↔ local)
without touching the pipeline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    @property
    def dimension(self) -> int | None:
        """Vector size, if known ahead of a call (else discovered on first embed)."""
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of chunk texts for indexing."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for retrieval."""
        ...
