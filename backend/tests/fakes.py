"""Port fakes for deterministic graph tests.

These mock the IO boundaries (embedder/vector/LLM) — NOT the subject under test, which is
the query graph + nodes. The generator is scripted so we can drive the critic loop exactly.
"""

from __future__ import annotations

from app.core.config import Settings
from app.domain.models import ScoredPoint, SparseVector
from app.services.query.state import Deps


class FakeEmbedder:
    dimension = 8

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * 8

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]


class FakeSparse:
    async def embed_query(self, text: str) -> SparseVector:
        return SparseVector(indices=[1], values=[1.0])

    async def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1], values=[1.0]) for _ in texts]


class FakeGraphStore:
    def __init__(self, enabled: bool = False, neighbors: list | None = None) -> None:
        self._enabled = enabled
        self._neighbors = neighbors or []
        self.calls: list[tuple[str, int]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def ensure_schema(self) -> None: ...
    async def clear_repo(self, ctx) -> None: ...
    async def upsert_graph(self, ctx, nodes, edges) -> None: ...

    async def neighbors(self, ctx, symbol: str, depth: int = 1) -> list:
        self.calls.append((symbol, depth))
        return list(self._neighbors)


class FakeVectorStore:
    def __init__(self, points: list[ScoredPoint]) -> None:
        self.points = points

    async def search_dense(self, ctx, vector, limit) -> list[ScoredPoint]:
        return self.points[:limit]

    async def search_sparse(self, ctx, vector, limit) -> list[ScoredPoint]:
        return self.points[:limit]

    async def ensure_collection(self, ctx, dense_dim) -> None: ...
    async def upsert(self, ctx, points) -> None: ...
    async def count(self, ctx) -> int:
        return len(self.points)

    async def delete_collection(self, ctx) -> None: ...


class FakeGenerator:
    """Returns scripted responses in order (generate, critic, generate, critic, ...)."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.responses.pop(0) if self.responses else '{"verdict":"fail","unsupported":[]}'


def make_point(
    *, path: str, symbol: str | None, text: str, start: int = 1, end: int = 3, index: int = 0
) -> ScoredPoint:
    return ScoredPoint(
        id=f"{path}:{index}",
        score=1.0,
        payload={
            "path": path,
            "symbol": symbol,
            "kind": "function_definition",
            "lang": "python",
            "start_line": start,
            "end_line": end,
            "index": index,
            "text": text,
        },
    )


def make_deps(
    points: list[ScoredPoint],
    responses: list[str],
    graph_store: FakeGraphStore | None = None,
    **settings_overrides,
) -> Deps:
    settings = Settings(rerank_enabled=False, **settings_overrides)
    return Deps(
        embedder=FakeEmbedder(),
        sparse=FakeSparse(),
        vectors=FakeVectorStore(points),
        generator=FakeGenerator(responses),
        graph_store=graph_store or FakeGraphStore(),
        settings=settings,
    )
