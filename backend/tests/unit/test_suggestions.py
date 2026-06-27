"""Suggestion generation — grounded in the repo's symbol map, with graceful fallback.

Behaviour/contract: parse the LLM's JSON questions; fall back (never raise) on empty repos,
bad output, or a generator error — the workspace must always get *something* to show.
"""

from __future__ import annotations

import pytest

from app.services import suggestions as svc
from app.services.suggestions import FALLBACK, build_digest, generate_suggestions

MAP = [("notes/store.py", ["NoteStore", "search"]), ("notes/ranking.py", ["Ranker"])]


class _Gen:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, system: str, user: str) -> str:
        return self.reply


@pytest.fixture(autouse=True)
def _clear_cache():
    svc._CACHE.clear()
    yield
    svc._CACHE.clear()


def test_digest_lists_symbols_per_file() -> None:
    digest = build_digest(MAP)
    assert "notes/store.py: NoteStore, search" in digest
    assert "notes/ranking.py: Ranker" in digest


async def test_parses_llm_json_questions() -> None:
    gen = _Gen('Here you go: ["How does NoteStore search?", "What does Ranker score?"]')
    out = await generate_suggestions("r1", MAP, generator=gen)
    assert out == ["How does NoteStore search?", "What does Ranker score?"]


async def test_empty_repo_returns_fallback_without_calling_llm() -> None:
    out = await generate_suggestions("r2", [], generator=_Gen("[]"))
    assert out == FALLBACK  # no symbols → no LLM call, generic fallback


async def test_garbage_output_falls_back() -> None:
    out = await generate_suggestions("r3", MAP, generator=_Gen("sorry, I can't"))
    assert out == FALLBACK  # no JSON array parsed → fallback, never raises


async def test_generator_error_falls_back() -> None:
    class _Boom:
        async def complete(self, system: str, user: str) -> str:
            raise RuntimeError("no api key")

    out = await generate_suggestions("r4", MAP, generator=_Boom())
    assert out == FALLBACK  # generator blew up → still returns something
