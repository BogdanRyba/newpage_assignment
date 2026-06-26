"""Retrieval-only path (no generation).

Used by the eval-runner to measure recall@k / MRR deterministically without invoking the
LLM. Mirrors the embed → retrieve → fuse → rerank → assemble portion of the graph.
"""

from __future__ import annotations

from app.domain.models import Hit, RepoContext
from app.domain.retrieval.context import Source, assemble
from app.domain.retrieval.fusion import reciprocal_rank_fusion
from app.services.query.nodes.retrieval import _to_hit
from app.services.query.state import Deps


async def retrieve_ranked(
    deps: Deps, repo_id: str, question: str
) -> tuple[list[Hit], list[Source]]:
    ctx = RepoContext(repo_id=repo_id)
    limit = deps.settings.retrieve_limit
    dense = await deps.embedder.embed_query(question)
    sparse = await deps.sparse.embed_query(question)
    dense_hits = [
        _to_hit(repo_id, sp, "dense") for sp in await deps.vectors.search_dense(ctx, dense, limit)
    ]
    sparse_hits = [
        _to_hit(repo_id, sp, "sparse")
        for sp in await deps.vectors.search_sparse(ctx, sparse, limit)
    ]
    fused = reciprocal_rank_fusion([dense_hits, sparse_hits], k=deps.settings.rrf_k)
    ranked = fused[: deps.settings.top_k]
    sources, _ = assemble(ranked, token_budget=deps.settings.token_budget)
    return ranked, sources
