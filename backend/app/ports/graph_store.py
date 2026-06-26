"""Port: code graph store (Neo4j adapter — STUB in MVP).

Designed in now so the `graph_augment` node has a seam to grow into (call/import
edges, structural queries). The MVP adapter is a no-op; the real graph is stretch.
All traversals will be scoped by `RepoContext.graph_namespace`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import RepoContext


@runtime_checkable
class GraphStore(Protocol):
    @property
    def enabled(self) -> bool:
        """False in MVP — callers skip graph augmentation when disabled."""
        ...

    async def neighbors(self, ctx: RepoContext, symbol: str, depth: int = 1) -> list[str]:
        """Symbols structurally related to `symbol` (callers/callees/imports)."""
        ...
