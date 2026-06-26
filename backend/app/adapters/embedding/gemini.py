"""Dense embedder adapter — Gemini via LangChain (implements the Embedder port).

The LangChain client is built lazily so replay-mode tests need no API key. All calls
go through the cassette boundary for deterministic, offline CI.
"""

from __future__ import annotations

from app.core.cassette import through_cassette
from app.core.config import get_settings


class GeminiEmbedder:
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.embedding_model
        self._api_key = api_key or settings.gemini_api_key
        self._client = None
        self._dim: int | None = None

    def _lazy_client(self):  # noqa: ANN202
        if self._client is None:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            self._client = GoogleGenerativeAIEmbeddings(
                model=self.model, google_api_key=self._api_key or None
            )
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
