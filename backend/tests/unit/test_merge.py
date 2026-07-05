"""merge_answers: union + dedup citations across parallel personas, remap markers.

Cite-or-refuse is preserved by construction — the merged citation set is exactly the union of
the (non-refused) sub-answers' citations, so the merged answer can never cite a source no
sub-agent grounded. All-refused → a refusal.
"""

from __future__ import annotations

import re

from app.domain.models import Answer, Citation, CodeLocation
from app.services.orchestrator.merge import merge_answers


def _cite(n: int, path: str, start: int, end: int, symbol: str | None = None) -> Citation:
    loc = CodeLocation(path=path, start_line=start, end_line=end)
    return Citation(n=n, location=loc, symbol=symbol)


def test_unions_and_dedups_citations_across_personas() -> None:
    a = Answer(
        text="NoteStore searches notes [1].",
        citations=[_cite(1, "store.py", 10, 20, "NoteStore")],
    )
    b = Answer(
        text="It was written by Ada [1]; ranking lives in ranking.py [2].",
        citations=[
            _cite(1, "store.py", 10, 20, "NoteStore"),
            _cite(2, "ranking.py", 1, 5, "rank"),
        ],
    )
    merged = merge_answers([("qa", a), ("dev_search", b)])

    # store.py:10-20 appears in both → one merged citation; ranking.py adds a second.
    assert len(merged.citations) == 2
    paths = sorted(c.location.path for c in merged.citations)
    assert paths == ["ranking.py", "store.py"]
    # Markers in the merged text all resolve to a real merged citation.
    nums = {c.n for c in merged.citations}
    for grp in re.findall(r"\[(\d+)\]", merged.text):
        assert int(grp) in nums


def test_remaps_markers_to_merged_numbers() -> None:
    # b's local [1] points at ranking.py; after merge store.py is [1], ranking.py is [2],
    # so b's text marker must be rewritten from [1] to [2].
    a = Answer(text="see store [1].", citations=[_cite(1, "store.py", 1, 2)])
    b = Answer(text="ranking here [1].", citations=[_cite(1, "ranking.py", 1, 2)])
    merged = merge_answers([("qa", a), ("research", b)])
    by_path = {c.location.path: c.n for c in merged.citations}
    assert f"[{by_path['ranking.py']}]" in merged.text
    assert f"[{by_path['store.py']}]" in merged.text


def test_all_refused_yields_refusal() -> None:
    a = Answer(text="no", refused=True, refusal_reason="no_sources")
    b = Answer(text="no", refused=True, refusal_reason="authorship_unavailable")
    merged = merge_answers([("qa", a), ("dev_search", b)])
    assert merged.refused
    assert merged.citations == []


def test_skips_refused_keeps_grounded() -> None:
    a = Answer(text="grounded [1].", citations=[_cite(1, "x.py", 1, 2)])
    b = Answer(text="no", refused=True, refusal_reason="no_sources")
    merged = merge_answers([("qa", a), ("dev_search", b)])
    assert not merged.refused
    assert len(merged.citations) == 1
