"""Port: hybrid vector store (raw Qdrant adapter implements this).

Stays behind a port because it's a volatile boundary, but Qdrant is used *raw* —
we control named vectors, collection-per-repo, and do RRF ourselves in the domain.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import RepoContext, ScoredPoint, SparseVector, VectorPoint


@runtime_checkable
class VectorStore(Protocol):
    async def ensure_collection(self, ctx: RepoContext, dense_dim: int) -> None:
        """Create the per-repo collection with named dense+sparse vectors.

        If it exists with a different dense dim (embedding model changed), recreate it.
        """
        ...

    async def upsert(self, ctx: RepoContext, points: list[VectorPoint]) -> None:
        """Idempotent upsert keyed by deterministic point IDs."""
        ...

    async def search_dense(
        self, ctx: RepoContext, vector: list[float], limit: int
    ) -> list[ScoredPoint]: ...

    async def search_sparse(
        self, ctx: RepoContext, vector: SparseVector, limit: int
    ) -> list[ScoredPoint]: ...

    async def count(self, ctx: RepoContext) -> int: ...

    async def delete_by_blob(self, ctx: RepoContext, blob_sha: str) -> None:
        """Delete all points of one blob (GC of an orphaned, no-longer-referenced blob)."""
        ...

    async def delete_collection(self, ctx: RepoContext) -> None: ...
