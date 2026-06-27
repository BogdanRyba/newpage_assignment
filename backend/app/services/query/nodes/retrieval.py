"""Retrieval-side nodes: embed, hybrid retrieve + fuse, rerank, graph_augment.

Each is a builder that closes over Deps and returns a `State -> partial State` node.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from app.core.instrument import instrument
from app.domain.models import Chunk, Hit, RepoContext, ScoredPoint
from app.domain.retrieval.fusion import reciprocal_rank_fusion
from app.services.query.state import Deps, QueryState

Node = Callable[[QueryState], Awaitable[dict]]

# Cheap dispatcher: structural questions ("who calls X", "blast radius") want deeper graph
# expansion; semantic questions stay at depth 1.
_STRUCTURAL = re.compile(
    r"\b(who calls|caller|callee|call graph|depend|import|used by|blast radius|reference)\b",
    re.IGNORECASE,
)


def _to_hit(repo_id: str, sp: ScoredPoint, source: str) -> Hit:
    p = sp.payload
    chunk = Chunk(
        repo_id=repo_id,
        path=p["path"],
        lang=p.get("lang", "text"),
        symbol=p.get("symbol"),
        kind=p.get("kind", "block"),
        start_line=p["start_line"],
        end_line=p["end_line"],
        text=p.get("text", ""),
        index=p.get("index", 0),
    )
    return Hit(chunk=chunk, score=sp.score, source=source)


def embed_node(deps: Deps) -> Node:
    @instrument("embed")
    async def _node(state: QueryState) -> dict:
        dense = await deps.embedder.embed_query(state.question)
        sparse = await deps.sparse.embed_query(state.question)
        return {"dense": dense, "sparse": sparse}

    return _node


def retrieve_node(deps: Deps) -> Node:
    @instrument("retrieve")
    async def _node(state: QueryState) -> dict:
        ctx = RepoContext(repo_id=state.repo_id)
        limit = deps.settings.retrieve_limit
        dense_sp = await deps.vectors.search_dense(ctx, state.dense, limit)
        sparse_sp = (
            await deps.vectors.search_sparse(ctx, state.sparse, limit) if state.sparse else []
        )
        dense_hits = [_to_hit(state.repo_id, sp, "dense") for sp in dense_sp]
        sparse_hits = [_to_hit(state.repo_id, sp, "sparse") for sp in sparse_sp]
        fused = reciprocal_rank_fusion([dense_hits, sparse_hits], k=deps.settings.rrf_k)
        return {"fused": fused}

    return _node


def rerank_node(deps: Deps) -> Node:
    """Cross-encoder rerank, gated by RERANK_ENABLED. Off → take top_k of the fused order."""

    @instrument("rerank")
    async def _node(state: QueryState) -> dict:
        top_k = deps.settings.top_k
        if not deps.settings.rerank_enabled or not state.fused:
            return {"ranked": state.fused[:top_k]}
        from app.adapters.rerank.cross_encoder import rerank

        ranked = await rerank(state.question, state.fused, top_k=top_k)
        return {"ranked": ranked}

    return _node


def graph_augment_node(deps: Deps) -> Node:
    """Augment retrieval with structurally-related symbols from the graph store.

    For the top hits, pull callers/callees/containers from Neo4j and add their chunks to the
    context. No-op (passthrough) when the graph store is disabled — the MVP path is unchanged.
    """

    @instrument("graph_augment")
    async def _node(state: QueryState) -> dict:
        if not deps.graph_store.enabled or not state.ranked:
            return {}
        ctx = RepoContext(repo_id=state.repo_id)
        depth = 2 if _STRUCTURAL.search(state.question) else 1
        seen = {h.chunk.point_id for h in state.ranked}
        additions: list[Hit] = []
        for hit in state.ranked[: deps.settings.graph_augment_top]:
            if not hit.chunk.symbol:
                continue
            for node in await deps.graph_store.neighbors(ctx, hit.chunk.symbol, depth=depth):
                if not node.text or node.point_id in seen:
                    continue
                seen.add(node.point_id)
                chunk = Chunk(
                    repo_id=state.repo_id,
                    path=node.path,
                    lang=node.lang,
                    symbol=node.symbol,
                    kind=node.kind,
                    start_line=node.start_line,
                    end_line=node.end_line,
                    text=node.text,
                )
                additions.append(Hit(chunk=chunk, score=0.0, source="graph"))
        if not additions:
            return {}
        return {"ranked": state.ranked + additions}

    return _node
