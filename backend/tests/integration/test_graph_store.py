"""Neo4j graph store — neighbors traversal + repo isolation (skips if Neo4j is unreachable).

Run with the graph profile:
    GRAPH_ENABLED=true docker compose --profile graph up -d neo4j postgres qdrant redis
    docker compose run --rm -e GRAPH_ENABLED=true api pytest -m integration -k graph_store
"""

from __future__ import annotations

import pytest

from app.domain.models import GraphEdge, GraphNode, RepoContext

pytestmark = pytest.mark.integration


def _node(
    symbol: str,
    line: int,
    lang: str = "python",
    path: str = "m.py",
    kind: str = "function_definition",
) -> GraphNode:
    return GraphNode(
        symbol=symbol,
        path=path,
        lang=lang,
        kind=kind,
        start_line=line,
        end_line=line + 1,
        text=f"symbol {symbol} in {path}",
        point_id=f"{path}:{line}",
    )


async def _store_or_skip():
    from app.adapters.graph.neo4j import Neo4jGraphStore

    store = Neo4jGraphStore()
    try:
        await store.verify()  # raises if Neo4j is unreachable (ensure_schema is best-effort)
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
            [GraphEdge(src="main", dst="helper", type="CALLS", src_lang="python")],
        )

        nb = await store.neighbors(ctx, "main", depth=1)
        assert any(n.symbol == "helper" for n in nb)
        assert all(n.symbol != "main" for n in nb)  # excludes the seed symbol

        # Isolation: another repo's namespace sees nothing.
        assert await store.neighbors(other, "main", depth=1) == []
    finally:
        await store.clear_repo(ctx)
        await store.aclose()


async def test_subtypes_enumeration_is_language_scoped() -> None:
    # Polymorphism: enumerate subclasses/implementations of `Ranker` by directed EXTENDS/IMPLEMENTS
    # traversal. The fixture has a Python AND a TypeScript `Ranker`/`OverlapRanker` (same names) —
    # the language-scoped edge upsert must keep them apart (no cross-language link).
    store = await _store_or_skip()
    ctx = RepoContext(repo_id="gpoly")
    try:
        await store.clear_repo(ctx)
        nodes = [
            _node("Ranker", 1, kind="class_definition"),
            _node("OverlapRanker", 10, kind="class_definition"),
            _node("TitleBoostRanker", 20, kind="class_definition"),
            _node("Ranker", 1, lang="typescript", path="api.ts", kind="interface_declaration"),
            _node("OverlapRanker", 10, lang="typescript", path="api.ts", kind="class_declaration"),
        ]
        edges = [
            GraphEdge(src="OverlapRanker", dst="Ranker", type="EXTENDS", src_lang="python"),
            GraphEdge(src="TitleBoostRanker", dst="Ranker", type="EXTENDS", src_lang="python"),
            GraphEdge(src="OverlapRanker", dst="Ranker", type="IMPLEMENTS", src_lang="typescript"),
        ]
        await store.upsert_graph(ctx, nodes, edges)

        subs = await store.subtypes_of(ctx, "Ranker", depth=2)
        assert {"OverlapRanker", "TitleBoostRanker"} <= {n.symbol for n in subs}

        # Collision-fix contract: no edge connects two different languages.
        async with store._driver.session() as s:  # noqa: SLF001 — test inspects the raw graph
            res = await s.run(
                "MATCH (a:Symbol {repo_id:$r})-[]->(b:Symbol {repo_id:$r}) "
                "WHERE a.lang <> b.lang RETURN count(*) AS n",
                r=ctx.graph_namespace,
            )
            rows = await res.values()
        assert rows[0][0] == 0  # the Python OverlapRanker never links to the TS Ranker
    finally:
        await store.clear_repo(ctx)
        await store.aclose()
