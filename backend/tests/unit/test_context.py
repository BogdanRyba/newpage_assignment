"""Context assembly — dedup, numbering, fencing, token budget."""

from __future__ import annotations

from app.domain.models import Chunk, Hit
from app.domain.retrieval.context import assemble


def _hit(symbol: str, text: str, path: str = "f.py", idx: int = 0) -> Hit:
    chunk = Chunk(
        repo_id="r",
        path=path,
        lang="python",
        symbol=symbol,
        kind="function_definition",
        start_line=1,
        end_line=3,
        text=text,
        index=idx,
    )
    return Hit(chunk=chunk, score=1.0, source="fused")


def test_numbers_sources_and_fences_them() -> None:
    sources, block = assemble([_hit("a", "def a(): ..."), _hit("b", "def b(): ...", idx=1)])
    assert [s.n for s in sources] == [1, 2]
    assert "[1]" in block and "[2]" in block
    assert "<<<SOURCE 1" in block and "SOURCE 1>>>" in block  # fenced as untrusted data


def test_dedup_same_path_and_symbol() -> None:
    sources, _ = assemble([_hit("a", "v1"), _hit("a", "v2")])
    assert len(sources) == 1  # same (path, symbol) collapses


def test_token_budget_trims_but_keeps_at_least_one() -> None:
    big = "x" * 5000
    sources, _ = assemble(
        [_hit("a", big), _hit("b", big, idx=1), _hit("c", big, idx=2)], token_budget=1000
    )
    assert len(sources) == 1  # ~4000 char budget, first source already exceeds → keep one
