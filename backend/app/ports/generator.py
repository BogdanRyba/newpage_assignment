"""Port: LLM text generation (LangChain/Gemini adapter implements this).

The only thing that ever sees assembled chunks. Used by the generate, critic, and judge
steps. We expose a single `complete()` — the validated answer is streamed to the client by
chunking it after the critic loop, so we don't need raw token streaming here (see DECISIONS).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Generator(Protocol):
    async def complete(self, system: str, user: str) -> str: ...
