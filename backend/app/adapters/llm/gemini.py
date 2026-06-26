"""LLM generator adapter — Gemini chat via LangChain (implements the Generator port).

Lazy client (replay needs no key) + cassette boundary (deterministic, offline CI).
Temperature 0 for reproducibility.
"""

from __future__ import annotations

from app.core.cassette import through_cassette
from app.core.config import get_settings


class GeminiGenerator:
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.llm_model
        self._api_key = api_key or settings.gemini_api_key
        self._client = None

    def _lazy_client(self):  # noqa: ANN202
        if self._client is None:
            from langchain_google_genai import ChatGoogleGenerativeAI

            self._client = ChatGoogleGenerativeAI(
                model=self.model, google_api_key=self._api_key or None, temperature=0.0
            )
        return self._client

    async def complete(self, system: str, user: str) -> str:
        async def produce() -> str:
            messages = [("system", system), ("human", user)]
            resp = await self._lazy_client().ainvoke(messages)
            return resp.content if isinstance(resp.content, str) else str(resp.content)

        return await through_cassette(
            "complete", self.model, {"system": system, "user": user}, produce
        )
