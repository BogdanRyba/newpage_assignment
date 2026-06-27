"""graph_augment node — passthrough when disabled, enriches ranked when enabled,
and the keyword dispatcher deepens traversal for structural questions."""

from __future__ import annotations

from app.domain.models import GraphNode
from app.services.query.graph import build_graph
from app.services.query.state import QueryState
from tests.fakes import FakeGraphStore, make_deps, make_point

CALC = make_point(
    path="calculator.py", symbol="add", text="def add(self, v): ...", start=10, end=12
)
NEIGHBOR = GraphNode(
    symbol="reset",
    path="calculator.py",
    lang="python",
    kind="function_definition",
    start_line=20,
    end_line=22,
    text="def reset(self):\n    self.total = 0",
    point_id="calculator.py:9",
)


async def _answer(deps):
    graph = build_graph(deps)
    state = QueryState(repo_id="r1", question="how does add work?", repo_name="sample")
    result = await graph.ainvoke(state, config={"recursion_limit": 16})
    return result["answer"]


async def test_disabled_graph_is_passthrough() -> None:
    gs = FakeGraphStore(enabled=False, neighbors=[NEIGHBOR])
    deps = make_deps(
        points=[CALC],
        responses=["add increments the total [1].", '{"verdict":"pass","unsupported":[]}'],
        graph_store=gs,
    )
    await _answer(deps)
    assert gs.calls == []  # never consulted when disabled


async def test_enabled_graph_augments_and_neighbor_is_citable() -> None:
    gs = FakeGraphStore(enabled=True, neighbors=[NEIGHBOR])
    # The neighbor (reset) becomes source [2]; the model cites it.
    deps = make_deps(
        points=[CALC],
        responses=[
            "add increments [1]; reset zeroes the total [2].",
            '{"verdict":"pass","unsupported":[]}',
        ],
        graph_store=gs,
    )
    answer = await _answer(deps)
    assert gs.calls and gs.calls[0][1] == 1  # semantic question → depth 1
    paths = {c.location.path for c in answer.citations}
    assert "calculator.py" in paths
    assert any(c.n == 2 for c in answer.citations)  # neighbor pulled in as a source


async def test_structural_question_uses_depth_2() -> None:
    gs = FakeGraphStore(enabled=True, neighbors=[])
    deps = make_deps(
        points=[CALC],
        responses=["NO_ANSWER"],  # content irrelevant; we assert the dispatcher depth
        graph_store=gs,
    )
    state = QueryState(repo_id="r1", question="who calls add?", repo_name="sample")
    await build_graph(deps).ainvoke(state, config={"recursion_limit": 16})
    assert gs.calls and gs.calls[0][1] == 2  # structural → depth 2
