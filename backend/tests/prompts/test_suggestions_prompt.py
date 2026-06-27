"""Prompt test — the suggestions prompt returns repo-grounded starter questions.

Recorded once, replayed deterministically (CASSETTE_MODE). Asserts the behavioural contract:
a JSON array of exactly 4 concrete questions derived from the given symbol map. Run/record:
    CASSETTE_MODE=record pytest tests/prompts
"""

from __future__ import annotations

import json
import re

from app.adapters.llm.gemini import GeminiGenerator
from app.prompts import suggestions

DIGEST = (
    "notes/store.py: NoteStore, search, add, get\n"
    "notes/ranking.py: Ranker, OverlapRanker, TitleBoostRanker, rank_notes\n"
    "notes/config.py: MAX_RESULTS, STOPWORDS\n"
    "web/api.ts: NoteDTO, searchNotes, createNote"
)
_ARRAY = re.compile(r"\[.*\]", re.S)
_GROUNDED = ("notestore", "ranker", "searchnotes", "stopwords", "max_results", "note", "rank")


async def test_suggestions_are_four_grounded_questions() -> None:
    gen = GeminiGenerator()
    out = await gen.complete(suggestions.SYSTEM, suggestions.build_user(DIGEST))
    match = _ARRAY.search(out)
    assert match, "expected a JSON array in the output"
    items = json.loads(match.group(0))
    assert isinstance(items, list) and len(items) == 4
    assert all(isinstance(q, str) and q.strip() for q in items)
    # Grounded in the provided map — at least one question names a real symbol/file from it.
    joined = " ".join(items).lower()
    assert any(tok in joined for tok in _GROUNDED)
