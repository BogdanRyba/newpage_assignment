"""Qdrant vector store adapter (implements the VectorStore port).

Raw qdrant-client on purpose: we control the topology — one collection per repo, named
`dense` + `sparse` vectors in a single collection, deterministic uuid5 point IDs (idempotent
upserts), and recreate-on-embedding-change. RRF fusion is done in the domain, not here.
"""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.models import RepoContext, ScoredPoint, SparseVector, VectorPoint

log = get_logger("qdrant")

DENSE = "dense"
SPARSE = "sparse"


class QdrantVectorStore:
    def __init__(self, url: str | None = None) -> None:
        self._client = AsyncQdrantClient(url=url or get_settings().qdrant_url)

    async def ensure_collection(self, ctx: RepoContext, dense_dim: int) -> None:
        name = ctx.qdrant_collection
        if await self._client.collection_exists(name):
            info = await self._client.get_collection(name)
            current = info.config.params.vectors[DENSE].size  # type: ignore[index]
            if current == dense_dim:
                return
            log.info("recreate_collection", collection=name, old_dim=current, new_dim=dense_dim)
            await self._client.delete_collection(name)

        await self._client.create_collection(
            collection_name=name,
            vectors_config={DENSE: qm.VectorParams(size=dense_dim, distance=qm.Distance.COSINE)},
            sparse_vectors_config={SPARSE: qm.SparseVectorParams()},
        )

    async def upsert(self, ctx: RepoContext, points: list[VectorPoint]) -> None:
        if not points:
            return
        structs = [
            qm.PointStruct(
                id=p.id,
                vector={
                    DENSE: p.dense,
                    SPARSE: qm.SparseVector(indices=p.sparse.indices, values=p.sparse.values),
                },
                payload=p.payload,
            )
            for p in points
        ]
        await self._client.upsert(collection_name=ctx.qdrant_collection, points=structs)

    async def search_dense(
        self, ctx: RepoContext, vector: list[float], limit: int
    ) -> list[ScoredPoint]:
        resp = await self._client.query_points(
            collection_name=ctx.qdrant_collection,
            query=vector,
            using=DENSE,
            limit=limit,
            with_payload=True,
        )
        return _to_scored(resp.points)

    async def search_sparse(
        self, ctx: RepoContext, vector: SparseVector, limit: int
    ) -> list[ScoredPoint]:
        resp = await self._client.query_points(
            collection_name=ctx.qdrant_collection,
            query=qm.SparseVector(indices=vector.indices, values=vector.values),
            using=SPARSE,
            limit=limit,
            with_payload=True,
        )
        return _to_scored(resp.points)

    async def count(self, ctx: RepoContext) -> int:
        if not await self._client.collection_exists(ctx.qdrant_collection):
            return 0
        res = await self._client.count(ctx.qdrant_collection)
        return res.count

    async def delete_collection(self, ctx: RepoContext) -> None:
        if await self._client.collection_exists(ctx.qdrant_collection):
            await self._client.delete_collection(ctx.qdrant_collection)

    async def aclose(self) -> None:
        await self._client.close()


def _to_scored(points: list) -> list[ScoredPoint]:
    return [ScoredPoint(id=str(p.id), score=p.score, payload=p.payload or {}) for p in points]
