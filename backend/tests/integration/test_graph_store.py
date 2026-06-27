"""Neo4j graph store — neighbors traversal + repo isolation (skips if Neo4j is unreachable).

Run with the graph profile:
    GRAPH_ENABLED=true docker compose --profile graph up -d neo4j postgres qdrant redis
    docker compose run --rm -e GRAPH_ENABLED=true api pytest -m integration tests/integration/test_graph_store.py
"""

from __future__ import annotations

import pytest

from app.domain.models import GraphEdge, GraphNode, RepoContext

pytestmark = pytest.mark.integration


def _node(symbol: str, line: int) -> GraphNode:
    return GraphNode(
        symbol=symbol,
        path="m.py",
        lang="python",
        kind="function_definition",
        start_line=line,
        end_line=line + 1,
        text=f"def {symbol}(): ...",
        point_id=f"m.py:{line}",
    )


async def _store_or_skip():
    from app.adapters.graph.neo4j import Neo4jGraphStore

    store = Neo4jGraphStore()
    try:
        await store.ensure_schema()
    except Exception as exc:  # noqa: BLE001
        await store.aclose()
        pytest.skip(f"neo4j unavailable: {exc}")
    return store


async def test_neighbors_and_repo_isolation() -> None:
    store = await _store_or_skip()
    ctx = RepoContext(repo_id="gtest")
    other = RepoContext(repo_id="gtest_other")
    try:
        await store.clear_repo(ctx)
        await store.clear_repo(other)
        await store.upsert_graph(
            ctx,
            [_node("main", 1), _node("helper", 10)],
            [GraphEdge(src="main", dst="helper", type="CALLS")],
        )

        nb = await store.neighbors(ctx, "main", depth=1)
        assert any(n.symbol == "helper" for n in nb)
        assert all(n.symbol != "main" for n in nb)  # excludes the seed symbol

        # Isolation: another repo's namespace sees nothing.
        assert await store.neighbors(other, "main", depth=1) == []
    finally:
        await store.clear_repo(ctx)
        await store.aclose()
