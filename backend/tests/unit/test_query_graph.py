"""Query graph (Daedalus) behaviour — happy path, scope refusal, and the critic loop.

Drives the real graph with fake ports; the scripted generator lets us exercise the
generator-critic decisions deterministically (no LLM, no network).
"""

from __future__ import annotations

from app.services.query.graph import build_graph
from app.services.query.state import QueryState
from tests.fakes import make_deps, make_point

CALC = make_point(
    path="calculator.py",
    symbol="add",
    text="def add(self, v):\n    self.total += v",
    start=10,
    end=12,
)


async def _run(deps, question="how does add work?", repo="sample"):
    graph = build_graph(deps)
    state = QueryState(repo_id="r1", question=question, repo_name=repo)
    result = await graph.ainvoke(state, config={"recursion_limit": 16})
    return result["answer"]


# --- positive ---


async def test_happy_path_returns_answer_with_citation() -> None:
    deps = make_deps(
        points=[CALC],
        responses=["add increments the running total [1].", '{"verdict":"pass","unsupported":[]}'],
    )
    answer = await _run(deps)
    assert not answer.refused
    assert "[1]" in answer.text
    assert [c.n for c in answer.citations] == [1]
    assert answer.citations[0].location.path == "calculator.py"


# --- negative / adversarial ---


async def test_empty_retrieval_refuses_with_no_sources() -> None:
    deps = make_deps(points=[], responses=[])
    answer = await _run(deps)
    assert answer.refused
    assert answer.refusal_reason == "no_sources"
    assert not answer.citations


async def test_critic_rejects_hallucinated_marker_then_regenerates() -> None:
    # First draft cites a non-existent [3]; critic loop forces a clean regeneration.
    deps = make_deps(
        points=[CALC],
        responses=[
            "the total is updated [3].",
            '{"verdict":"pass","unsupported":[]}',
            "add increments the running total [1].",
            '{"verdict":"pass","unsupported":[]}',
        ],
        max_critic_iterations=2,
    )
    answer = await _run(deps)
    assert not answer.refused
    assert "[3]" not in answer.text
    assert [c.n for c in answer.citations] == [1]
    assert len(deps.generator.calls) == 4  # 2x (generate + critic)


async def test_valid_citations_survive_an_overeager_critic() -> None:
    # The LLM judge flags the only sentence as unsupported every round, but its citation [1]
    # is deterministically valid → trust the valid citation rather than false-refuse.
    deps = make_deps(
        points=[CALC],
        responses=[
            "add increments the running total [1].",
            '{"verdict":"fail","unsupported":["add increments the running total"]}',
            "add increments the running total [1].",
            '{"verdict":"fail","unsupported":["add increments the running total"]}',
        ],
        max_critic_iterations=1,
    )
    answer = await _run(deps)
    assert not answer.refused
    assert [c.n for c in answer.citations] == [1]


async def test_unsupported_after_retries_drops_to_refusal() -> None:
    # Every draft only cites a hallucinated marker → nothing valid survives → refuse.
    deps = make_deps(
        points=[CALC],
        responses=[
            "totally made up [9].",
            '{"verdict":"fail","unsupported":["totally made up"]}',
            "still made up [9].",
            '{"verdict":"fail","unsupported":["still made up"]}',
        ],
        max_critic_iterations=1,
    )
    answer = await _run(deps)
    assert answer.refused
    assert answer.refusal_reason == "insufficient_support"
