"""Neo4j graph store adapter — STUB (implements the GraphStore port).

The seam for graph-augmented retrieval (stretch). In MVP it's disabled, so the
`graph_augment` node is a passthrough. When implemented, nodes will carry a `repo_id`
property and every traversal will filter on `ctx.graph_namespace` for isolation.
"""

from __future__ import annotations

from app.domain.models import RepoContext


class Neo4jGraphStoreStub:
    @property
    def enabled(self) -> bool:
        return False

    async def neighbors(self, ctx: RepoContext, symbol: str, depth: int = 1) -> list[str]:
        return []
