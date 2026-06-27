"""Citation build / validity / pruning — the backbone of 'trust comes from sources'."""

from __future__ import annotations

from app.domain.citation.service import (
    build_citations,
    check_validity,
    drop_unsupported,
    markers_in,
)
from app.domain.retrieval.context import Source

SOURCES = [
    Source(
        n=1, path="calc.py", symbol="add", lang="python", start_line=10, end_line=12, text="..."
    ),
    Source(
        n=2, path="calc.py", symbol="divide", lang="python", start_line=20, end_line=25, text="."
    ),
]


def test_build_citations_maps_markers_to_sources() -> None:
    cites = build_citations("add updates the total [1]; divide guards zero [2].", SOURCES)
    assert [c.n for c in cites] == [1, 2]
    assert cites[0].location.label == "calc.py:10-12"
    assert cites[0].symbol == "add"


def test_grouped_citation_markers_are_parsed() -> None:
    # Regression: the LLM writes grouped citations like "[1, 3]" — these must be recognised,
    # not treated as zero markers (which caused false "no citations" → needless refusal).
    assert markers_in("ranks then returns [1, 2] done") == [1, 2]
    assert markers_in("a [1] and b [2]") == [1, 2]
    check = check_validity("NoteStore ranks and returns the top results [1, 2].", SOURCES)
    assert check.has_any and check.is_valid and check.invalid_markers == []
    cites = build_citations("ranks and returns [1, 2].", SOURCES)
    assert [c.n for c in cites] == [1, 2]


def test_valid_answer_passes_check() -> None:
    check = check_validity("add does X [1].", SOURCES)
    assert check.is_valid and check.has_any and check.invalid_markers == []


def test_hallucinated_marker_is_invalid() -> None:
    check = check_validity("this is claimed [5].", SOURCES)
    assert not check.is_valid
    assert check.invalid_markers == [5]


def test_uncited_answer_is_invalid() -> None:
    check = check_validity("add updates the total.", SOURCES)
    assert not check.has_any and not check.is_valid


def test_drop_unsupported_keeps_only_valid_supported_sentences() -> None:
    text = "add updates the total [1]. divide is unrelated [2]. floats are fast [5]."
    pruned = drop_unsupported(text, SOURCES, unsupported=["divide is unrelated"])
    assert "add updates the total [1]." in pruned
    assert "divide is unrelated" not in pruned  # critic-flagged
    assert "[5]" not in pruned  # hallucinated marker
