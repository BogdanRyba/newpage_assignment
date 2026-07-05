"""Tool registry — the planner's action space, backed by OUR ports (LangChain stays LLM-only).

The LLM never gets tool-binding or raw FS/repo access: it sees only each tool's name +
description (text in the planner prompt) and emits {action, params}; this registry validates
the name, runs the matching port-backed function, and returns a ToolResult carrying grounded
Sources (the same type the citation layer consumes) plus a short, sanitized summary fed back to
the planner. Unknown tools are ignored (ok=False), so an injected "call rm_rf" can't do harm.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from app.domain.models import RepoContext
from app.domain.retrieval.context import Source, assemble
from app.domain.retrieval.fusion import reciprocal_rank_fusion
from app.services.query.nodes.retrieval import _to_hit
from app.services.query.state import Deps

ToolFn = Callable[[Deps, RepoContext, dict], Awaitable["ToolResult"]]


class ToolSpec(BaseModel):
    name: str
    description: str  # shown to the planner
    params_schema: dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool: str
    ok: bool
    sources: list[Source] = Field(default_factory=list)
    summary: str = ""


class ToolRegistry:
    def __init__(self, deps: Deps) -> None:
        self._deps = deps
        self._tools: dict[str, tuple[ToolSpec, ToolFn]] = {}
        self.calls: list[str] = []  # names invoked (handy for tests/telemetry)

    def register(self, spec: ToolSpec, fn: ToolFn) -> None:
        self._tools[spec.name] = (spec, fn)

    def specs_for_prompt(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    async def invoke(self, ctx: RepoContext, name: str, params: dict) -> ToolResult:
        self.calls.append(name)
        entry = self._tools.get(name)
        if entry is None:  # unknown / injected tool name → no-op, never raises
            return ToolResult(tool=name, ok=False, summary="unknown tool")
        _spec, fn = entry
        try:
            return await fn(self._deps, ctx, params or {})
        except Exception as exc:  # noqa: BLE001 — a tool failure must not crash the run
            return ToolResult(tool=name, ok=False, summary=str(exc)[:120])


# --- port-backed tools ---


async def _retrieval(deps: Deps, ctx: RepoContext, params: dict) -> ToolResult:
    query = str(params.get("query", "")).strip()
    dense = await deps.embedder.embed_query(query)
    sparse = await deps.sparse.embed_query(query)
    limit = deps.settings.retrieve_limit
    dense_sp = await deps.vectors.search_dense(ctx, dense, limit)
    dense_hits = [_to_hit(ctx.repo_id, sp, "dense") for sp in dense_sp]
    sparse_hits = []
    if sparse:
        sparse_sp = await deps.vectors.search_sparse(ctx, sparse, limit)
        sparse_hits = [_to_hit(ctx.repo_id, sp, "sparse") for sp in sparse_sp]
    fused = reciprocal_rank_fusion([dense_hits, sparse_hits], k=deps.settings.rrf_k)
    sources, _block = assemble(
        fused[: deps.settings.top_k], token_budget=deps.settings.token_budget
    )
    return ToolResult(
        tool="retrieval", ok=True, sources=sources, summary=f"{len(sources)} sources"
    )


async def _graph_neighbors(deps: Deps, ctx: RepoContext, params: dict) -> ToolResult:
    if not deps.graph_store.enabled:
        return ToolResult(tool="graph_neighbors", ok=False, summary="graph store disabled")
    symbol = str(params.get("symbol", "")).strip()
    nodes = await deps.graph_store.neighbors(ctx, symbol, depth=1)
    sources = [
        Source(
            n=i + 1, path=nd.path, symbol=nd.symbol, lang=nd.lang,
            start_line=nd.start_line, end_line=nd.end_line, text=nd.text,
        )
        for i, nd in enumerate(nodes)
    ]
    return ToolResult(
        tool="graph_neighbors", ok=True, sources=sources, summary=f"{len(nodes)} related symbols"
    )


async def _authorship_lookup(deps: Deps, ctx: RepoContext, params: dict) -> ToolResult:
    if deps.authorship is None or not deps.authorship.enabled:
        return ToolResult(tool="authorship_lookup", ok=False, summary="authorship unavailable")
    path = str(params.get("path", "")).strip()
    fa = await deps.authorship.file_authorship(ctx, path)
    if fa is None:
        return ToolResult(tool="authorship_lookup", ok=True, summary=f"no authorship for {path}")
    return ToolResult(
        tool="authorship_lookup", ok=True,
        summary=f"{fa.path}: last changed by {fa.last_author} ({fa.last_commit_sha[:8]})",
    )


def default_registry(deps: Deps) -> ToolRegistry:
    reg = ToolRegistry(deps)
    reg.register(
        ToolSpec(
            name="retrieval",
            description="Hybrid search the repo for code relevant to a query.",
            params_schema={"query": "string"},
        ),
        _retrieval,
    )
    reg.register(
        ToolSpec(
            name="graph_neighbors",
            description="Symbols related to a symbol (callers/callees/contains) via the graph.",
            params_schema={"symbol": "string"},
        ),
        _graph_neighbors,
    )
    reg.register(
        ToolSpec(
            name="authorship_lookup",
            description="Who last changed a file and its recent commit history.",
            params_schema={"path": "string"},
        ),
        _authorship_lookup,
    )
    return reg
