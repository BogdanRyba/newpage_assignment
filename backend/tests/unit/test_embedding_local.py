"""Local embedder contract — subword matching + contextual-header boost.

The offline embedder must rank the chunk that *defines* a symbol above one that merely repeats
common tokens; that's what makes the deterministic eval gate's MRR meaningful (D-016). These fail
if the header boost or subword split regresses.
"""

from __future__ import annotations

from app.adapters.embedding.local import LocalHashEmbedder
from app.domain.chunking.service import with_context

EMB = LocalHashEmbedder()


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are L2-normalised → dot = cosine


async def _vec(text: str) -> list[float]:
    return await EMB.embed_query(text)


async def test_header_symbol_outranks_body_token_spam() -> None:
    # The chunk whose header names NoteStore must beat one that merely repeats "search/notes".
    defines = with_context(
        "notes/store.py", "NoteStore", "def search(self, q):\n    return rank(q)"
    )
    spam = with_context(
        "notes/ranking.py", "rank_notes", "search search search results notes notes terms"
    )
    q = await _vec("How does NoteStore search for notes?")
    assert _cos(q, await _vec(defines)) > _cos(q, await _vec(spam))


async def test_boost_is_symbol_specific_not_any_header() -> None:
    # Control: a boosted header doesn't win by itself — querying NoteStore must not rank an
    # unrelated TagIndex chunk above it.
    store = with_context("notes/store.py", "NoteStore", "def search(self):\n    return 1")
    other = with_context("notes/tags.py", "TagIndex", "def lookup(self):\n    return 1")
    q = await _vec("NoteStore")
    assert _cos(q, await _vec(store)) > _cos(q, await _vec(other))


async def test_module_chunk_body_constant_still_retrievable() -> None:
    # Module chunks have no symbol (header is just `# path`); a distinctive body constant must
    # still rank the chunk above an unrelated one — the header boost didn't drown out body tokens.
    cfg = with_context("notes/config.py", None, "STOPWORDS = {'the', 'a'}\nMAX_RESULTS = 20")
    other = with_context("notes/models.py", "Note", "class Note:\n    title: str")
    q = await _vec("stopwords")
    assert _cos(q, await _vec(cfg)) > _cos(q, await _vec(other))


async def test_subword_split_matches_camel_and_snake_case() -> None:
    # "create note" ↔ createNote still holds (D-015), independent of the header boost.
    q = await _vec("create note")
    hit = await _vec(with_context("web/api.ts", "createNote", "export function createNote() {}"))
    miss = await _vec(with_context("web/api.ts", "deleteTag", "export function deleteTag() {}"))
    assert _cos(q, hit) > _cos(q, miss)
