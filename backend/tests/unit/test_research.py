"""Research persona graph: structural questions pull graph neighbors into the cited sources."""

from __future__ import annotations

from app.domain.models import GraphNode
from app.services.query.graph import build_research_graph
from app.services.query.state import QueryState
from tests.fakes import FakeGraphStore, make_deps, make_point


async def test_research_surfaces_graph_neighbors_in_sources() -> None:
    neighbor = GraphNode(
        symbol="rerank",
        path="retrieval/rerank.py",
        lang="python",
        kind="function_definition",
        start_line=1,
        end_line=8,
        text="def rerank(hits): ...",
        point_id="p-neighbor",
    )
    point = make_point(path="query/graph.py", symbol="build_graph", text="def build_graph(): ...")
    deps = make_deps(
        points=[point],
        responses=["build_graph calls rerank [1].", '{"verdict":"pass","unsupported":[]}'],
        graph_store=FakeGraphStore(enabled=True, neighbors=[neighbor]),
    )
    graph = build_research_graph(deps)
    state = QueryState(repo_id="r1", question="what calls rerank?")
    result = await graph.ainvoke(state, config={"recursion_limit": 16})

    answer = result["answer"]
    assert not answer.refused
    # The graph-expanded neighbor was pulled in as a retrievable source.
    source_paths = {s.path for s in result["sources"]}
    assert "retrieval/rerank.py" in source_paths


async def test_research_refuses_when_no_hits() -> None:
    deps = make_deps(
        points=[],  # nothing retrieved → scope refuse
        responses=[],
        graph_store=FakeGraphStore(enabled=True, neighbors=[]),
    )
    graph = build_research_graph(deps)
    state = QueryState(repo_id="r1", question="what depends on nothing?")
    result = await graph.ainvoke(state, config={"recursion_limit": 16})
    assert result["answer"].refused
