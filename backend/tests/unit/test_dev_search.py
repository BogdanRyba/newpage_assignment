"""Dev-search persona graph: grounded authorship answers.

Drives the REAL dev-search graph with fake ports (we mock IO, not the subject). Covers:
positive (attributes the real author), negative (no authorship → refuse), and the headline
adversarial case (LLM invents an author not in git → guard rejects → final answer never
contains the fabricated name).
"""

from __future__ import annotations

from app.domain.models import CommitRef, FileAuthorship
from app.services.query.dev_graph import build_dev_search_graph
from app.services.query.state import QueryState
from tests.fakes import FakeAuthorship, make_deps, make_point

PATH = "notes/store.py"
_FA = FileAuthorship(
    path=PATH,
    last_author="Ada Lovelace",
    last_author_email="ada@x.io",
    last_commit_sha="abc123def456",
    last_commit_at="2024-01-02T00:00:00+00:00",
    recent_commits=[CommitRef(sha="abc123def456", author="Ada Lovelace", subject="add search")],
)


async def _run(responses, authorship):  # noqa: ANN001, ANN202
    deps = make_deps(
        points=[make_point(path=PATH, symbol="NoteStore", text="class NoteStore: ...")],
        responses=responses,
        authorship=authorship,
    )
    graph = build_dev_search_graph(deps)
    state = QueryState(repo_id="r1", question="who wrote NoteStore?")
    result = await graph.ainvoke(state, config={"recursion_limit": 16})
    return result["answer"]


async def test_positive_attributes_real_author() -> None:
    answer = await _run(
        responses=["NoteStore was written by @author{Ada Lovelace} in @commit{abc123def456} [1]."],
        authorship=FakeAuthorship({PATH: _FA}),
    )
    assert not answer.refused
    assert "Ada Lovelace" in answer.text
    assert answer.citations and answer.citations[0].location.path == PATH


async def test_no_authorship_refuses() -> None:
    answer = await _run(
        responses=["irrelevant"],
        authorship=FakeAuthorship({}),  # no records for the located file
    )
    assert answer.refused
    assert answer.refusal_reason == "authorship_unavailable"


async def test_hallucinated_author_never_reaches_final_answer() -> None:
    # The LLM stubbornly names someone not in git on every attempt → the deterministic guard
    # rejects, retries are exhausted, and the factual fallback (built only from real records)
    # is returned. "Mallory" must never appear.
    answer = await _run(
        responses=[
            "Written by @author{Mallory} [1].",
            "Definitely @author{Mallory} [1].",
            "Still @author{Mallory} [1].",
        ],
        authorship=FakeAuthorship({PATH: _FA}),
    )
    assert "Mallory" not in answer.text
    assert "Ada Lovelace" in answer.text  # fallback attributes the real author
