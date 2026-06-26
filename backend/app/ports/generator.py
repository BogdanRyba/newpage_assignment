"""Port: LLM text generation (LangChain/Gemini adapter implements this).

The only thing that ever sees assembled chunks. Used by the generate/critic nodes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class Generator(Protocol):
    async def complete(self, system: str, user: str) -> str:
        """One-shot completion (used by the critic / judge)."""
        ...

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """Token stream (used by the synthesis node for SSE)."""
        ...
