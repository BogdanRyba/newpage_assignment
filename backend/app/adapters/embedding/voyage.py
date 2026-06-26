"""Dense embedder adapter — Voyage (code-specialised alternative behind the port).

Documented swap for `EMBEDDING_PROVIDER=voyage`. Kept thin and lazily imported so the
default Gemini path carries no Voyage dependency. `voyage-code-3` gives stronger recall
on pure code; we default to Gemini for the one-key demo (see docs/DECISIONS.md D-003).
"""

from __future__ import annotations

from app.core.cassette import through_cassette
from app.core.config import get_settings


class VoyageEmbedder:
    def __init__(self, model: str = "voyage-code-3", api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model
        self._api_key = api_key or settings.voyage_api_key
        self._client = None
        self._dim: int | None = None

    def _lazy_client(self):  # noqa: ANN202
        if self._client is None:
            try:
                from langchain_voyageai import VoyageAIEmbeddings
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "EMBEDDING_PROVIDER=voyage requires `langchain-voyageai`. "
                    "Add it to pyproject (note the reason in DECISIONS) and set VOYAGE_API_KEY."
                ) from exc
            self._client = VoyageAIEmbeddings(model=self.model, api_key=self._api_key or None)
        return self._client

    @property
    def dimension(self) -> int | None:
        return self._dim

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = await through_cassette(
            "embed_documents",
            self.model,
            texts,
            lambda: self._lazy_client().aembed_documents(texts),
        )
        if result:
            self._dim = len(result[0])
        return result

    async def embed_query(self, text: str) -> list[float]:
        result = await through_cassette(
            "embed_query", self.model, text, lambda: self._lazy_client().aembed_query(text)
        )
        self._dim = len(result)
        return result
