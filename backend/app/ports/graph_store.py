"""Port: code graph store (Neo4j adapter; no-op stub when disabled).

Designed in from day one so the `graph_augment` node has a seam. Implemented in the graph
phase: nodes carry `repo_id`; every traversal is scoped by `ctx.graph_namespace`, so no
edges ever connect symbols across repos.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import GraphEdge, GraphNode, RepoContext


@runtime_checkable
class GraphStore(Protocol):
    @property
    def enabled(self) -> bool:
        """False in MVP — callers skip graph augmentation when disabled."""
        ...

    async def ensure_schema(self) -> None: ...

    async def clear_repo(self, ctx: RepoContext) -> None:
        """Drop a repo's subgraph before re-ingest (idempotent)."""
        ...

    async def upsert_graph(
        self, ctx: RepoContext, nodes: list[GraphNode], edges: list[GraphEdge]
    ) -> None: ...

    async def neighbors(self, ctx: RepoContext, symbol: str, depth: int = 1) -> list[GraphNode]:
        """Symbols structurally related to `symbol` (callers/callees/containers), repo-scoped."""
        ...

    async def subtypes_of(self, ctx: RepoContext, symbol: str, depth: int = 2) -> list[GraphNode]:
        """Concrete subtypes of `symbol` (directed EXTENDS/IMPLEMENTS traversal), repo-scoped."""
        ...
