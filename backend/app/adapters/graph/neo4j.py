"""Neo4j graph store adapter (+ a no-op stub for MVP).

Stores one `:Symbol` node per code symbol, tagged with `repo_id`, plus CALLS/CONTAINS edges.
Every query filters on `repo_id` (from `ctx.graph_namespace`) so subgraphs never cross repos.
Nodes carry their chunk text so `graph_augment` can enrich context without another DB hop.

Enabled via `GRAPH_ENABLED=true` (run Neo4j with `docker compose --profile graph up`).
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.models import GraphEdge, GraphNode, RepoContext

log = get_logger("neo4j")


class Neo4jGraphStoreStub:
    """Used in MVP / when GRAPH_ENABLED is false — graph_augment becomes a passthrough."""

    @property
    def enabled(self) -> bool:
        return False

    async def ensure_schema(self) -> None: ...
    async def clear_repo(self, ctx: RepoContext) -> None: ...
    async def upsert_graph(
        self, ctx: RepoContext, nodes: list[GraphNode], edges: list[GraphEdge]
    ) -> None: ...

    async def neighbors(self, ctx: RepoContext, symbol: str, depth: int = 1) -> list[GraphNode]:
        return []


class Neo4jGraphStore:
    def __init__(self, uri: str | None = None, auth: str | None = None) -> None:
        from neo4j import AsyncGraphDatabase

        settings = get_settings()
        user, _, password = (auth or settings.neo4j_auth).partition("/")
        self._driver = AsyncGraphDatabase.driver(uri or settings.neo4j_uri, auth=(user, password))

    @property
    def enabled(self) -> bool:
        return True

    async def ensure_schema(self) -> None:
        # Best-effort: composite uniqueness support varies by Neo4j edition/version. MERGE works
        # without it (just less enforced), so a constraint failure must not break ingest.
        async with self._driver.session() as s:
            try:
                await s.run(
                    "CREATE CONSTRAINT symbol_key IF NOT EXISTS "
                    "FOR (n:Symbol) REQUIRE (n.repo_id, n.path, n.symbol) IS UNIQUE"
                )
            except Exception as exc:  # noqa: BLE001
                log.info("constraint_skipped", error=str(exc))

    async def clear_repo(self, ctx: RepoContext) -> None:
        async with self._driver.session() as s:
            await s.run("MATCH (n:Symbol {repo_id: $r}) DETACH DELETE n", r=ctx.graph_namespace)

    async def upsert_graph(
        self, ctx: RepoContext, nodes: list[GraphNode], edges: list[GraphEdge]
    ) -> None:
        repo = ctx.graph_namespace
        async with self._driver.session() as s:
            await s.run(
                """
                UNWIND $nodes AS n
                MERGE (x:Symbol {repo_id: $r, path: n.path, symbol: n.symbol})
                SET x.lang = n.lang, x.kind = n.kind, x.start_line = n.start_line,
                    x.end_line = n.end_line, x.text = n.text, x.point_id = n.point_id
                """,
                r=repo,
                nodes=[n.model_dump() for n in nodes],
            )
            # One statement per edge type (relationship type can't be parameterized in Cypher;
            # the small fixed set {CALLS, CONTAINS} is interpolated, never user input).
            for etype in {e.type for e in edges}:
                pairs = [{"src": e.src, "dst": e.dst} for e in edges if e.type == etype]
                await s.run(
                    f"""
                    UNWIND $pairs AS p
                    MATCH (a:Symbol {{repo_id: $r, symbol: p.src}})
                    MATCH (b:Symbol {{repo_id: $r, symbol: p.dst}})
                    MERGE (a)-[:{etype}]->(b)
                    """,
                    r=repo,
                    pairs=pairs,
                )

    async def neighbors(self, ctx: RepoContext, symbol: str, depth: int = 1) -> list[GraphNode]:
        depth = max(1, min(depth, 2))
        async with self._driver.session() as s:
            result = await s.run(
                f"""
                MATCH (s:Symbol {{repo_id: $r, symbol: $sym}})
                MATCH (s)-[:CALLS|CONTAINS*1..{depth}]-(n:Symbol)
                WHERE n.symbol <> $sym
                RETURN DISTINCT n LIMIT 8
                """,
                r=ctx.graph_namespace,
                sym=symbol,
            )
            records = await result.values()
        out: list[GraphNode] = []
        for (node,) in records:
            out.append(
                GraphNode(
                    symbol=node["symbol"],
                    path=node["path"],
                    lang=node.get("lang", "text"),
                    kind=node.get("kind", "block"),
                    start_line=node.get("start_line", 1),
                    end_line=node.get("end_line", 1),
                    text=node.get("text", ""),
                    point_id=node.get("point_id", ""),
                )
            )
        return out

    async def verify(self) -> None:
        """Raise if Neo4j is unreachable (used to gate tests; not best-effort)."""
        await self._driver.verify_connectivity()

    async def aclose(self) -> None:
        await self._driver.close()
