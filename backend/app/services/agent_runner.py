"""AgentRunner — the Daedalus facade (harness component 7).

One entry point that stitches the compiled graph + budgets/limits (recursion limit, request
timeout). Both the API and the eval-runner call this same path, so prod and tests exercise
identical code. Deps are injectable so tests can supply fakes.

The validated answer is streamed to the client by chunking it AFTER the critic loop — we never
stream an unvalidated draft the critic might rewrite (see DECISIONS).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.core.config import get_settings
from app.core.factory import (
    make_embedder,
    make_generator,
    make_graph_store,
    make_sparse_embedder,
    make_vector_store,
)
from app.domain.models import Answer
from app.services.query.graph import build_graph
from app.services.query.state import Deps, QueryState

RECURSION_LIMIT = 16


def default_deps() -> Deps:
    settings = get_settings()
    return Deps(
        embedder=make_embedder(),
        sparse=make_sparse_embedder(),
        vectors=make_vector_store(),
        generator=make_generator(),
        graph_store=make_graph_store(),
        settings=settings,
    )


class AgentRunner:
    def __init__(self, deps: Deps | None = None) -> None:
        self.deps = deps or default_deps()
        self.graph = build_graph(self.deps)

    async def run(self, repo_id: str, question: str, repo_name: str | None = None) -> Answer:
        state = QueryState(repo_id=repo_id, question=question, repo_name=repo_name)
        timeout = self.deps.settings.request_timeout_s
        async with asyncio.timeout(timeout):
            result = await self.graph.ainvoke(state, config={"recursion_limit": RECURSION_LIMIT})
        answer = (
            result.get("answer") if isinstance(result, dict) else getattr(result, "answer", None)
        )
        return answer or Answer(text="No answer produced.", refused=True, refusal_reason="empty")

    async def stream(
        self, repo_id: str, question: str, repo_name: str | None = None
    ) -> AsyncIterator[dict]:
        """Stream the agent's progress, then its validated answer.

        Each graph node is surfaced as a `status` event (the "thinking" trace) so the UI shows
        what Daedalus is doing during the multi-second run — including the critic re-grounding a
        claim — instead of a frozen cursor. We still only stream the *validated* answer text after
        the critic loop settles, never an unvalidated draft (see DECISIONS).
        """
        state = QueryState(repo_id=repo_id, question=question, repo_name=repo_name)
        answer: Answer | None = None
        async with asyncio.timeout(self.deps.settings.request_timeout_s):
            async for chunk in self.graph.astream(
                state, stream_mode="updates", config={"recursion_limit": RECURSION_LIMIT}
            ):
                for node, raw in chunk.items():
                    update = raw if isinstance(raw, dict) else {}
                    if update.get("answer") is not None:
                        answer = update["answer"]
                    event = _status_event(node, update)
                    if event:
                        yield event

        answer = answer or Answer(text="No answer produced.", refused=True, refusal_reason="empty")
        words = answer.text.split(" ")
        for i in range(0, len(words), 3):
            yield {"type": "token", "text": " ".join(words[i : i + 3]) + " "}
        if answer.citations:
            yield {
                "type": "citations",
                "citations": [
                    {
                        "n": c.n,
                        "path": c.location.path,
                        "start": c.location.start_line,
                        "end": c.location.end_line,
                        "symbol": c.symbol,
                        "label": c.location.label,
                    }
                    for c in answer.citations
                ],
            }
        elif answer.refused:
            yield {"type": "no_sources", "reason": answer.refusal_reason}
        yield {"type": "done"}


def _status_event(node: str, update: dict) -> dict | None:
    """Map a graph node's partial update to a human-readable 'thinking' status event (or None).

    Counts/feedback come from the node's own state, so the trace reflects what actually happened
    (candidates found, sources read, a critic regeneration) — not a canned spinner.
    """
    if node == "embed":
        return {"type": "status", "label": "Understanding the question"}
    if node == "retrieve":
        n = len(update.get("fused") or [])
        return {"type": "status", "label": "Searching the hybrid index", "detail": f"{n} chunks"}
    if node == "graph_augment":
        # Only when the graph store actually pulled in related symbols (enabled + matches).
        if update.get("ranked"):
            return {"type": "status", "label": "Expanding via the code graph"}
        return None
    if node == "assemble":
        n = len(update.get("sources") or [])
        return {
            "type": "status",
            "label": "Reading sources",
            "detail": f"{n} source{'' if n == 1 else 's'}",
        }
    if node == "generate":
        return {"type": "status", "label": "Drafting the answer"}
    if node == "critic":
        if update.get("answer") is not None:
            return {"type": "status", "label": "Validating citations"}
        return {
            "type": "status",
            "label": "Refining — a claim wasn't grounded",
            "detail": f"attempt {update.get('critic_iters', 1)}",
        }
    if node == "scope_refuse":
        return {"type": "status", "label": "No matching sources in this repo"}
    return None
