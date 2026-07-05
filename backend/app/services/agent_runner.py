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
    make_authorship,
    make_embedder,
    make_generator,
    make_graph_store,
    make_sparse_embedder,
    make_vector_store,
)
from app.domain.models import Answer
from app.services.coordinator.router import classify_intent
from app.services.orchestrator.crisis import escalation_answer, should_escalate
from app.services.orchestrator.merge import merge_answers
from app.services.query.dev_graph import build_dev_search_graph
from app.services.query.graph import build_architect_graph, build_graph, build_research_graph
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
        authorship=make_authorship(),
    )


class AgentRunner:
    def __init__(self, deps: Deps | None = None) -> None:
        self.deps = deps or default_deps()
        self.graph = build_graph(self.deps)
        self.dev_graph = build_dev_search_graph(self.deps)
        self.research_graph = build_research_graph(self.deps)
        self.architect_graph = build_architect_graph(self.deps)

    def _graph_for(self, persona: str):  # noqa: ANN202 — compiled LangGraph
        if persona == "dev_search":
            return self.dev_graph
        if persona == "research":
            return self.research_graph
        if persona == "architect":
            return self.architect_graph
        return self.graph

    def _route(self, question: str):  # noqa: ANN202 — compiled LangGraph + intent
        """Pick the persona graph. Coordinator off → always QA (Daedalus)."""
        if not self.deps.settings.coordinator_enabled:
            return self.graph, "qa"
        intent = classify_intent(question)
        if intent == "dev_search" and not self.deps.settings.dev_search_enabled:
            intent = "qa"
        return self._graph_for(intent), intent

    def _select_personas(self, question: str) -> list[str]:
        """Which personas to fan out to (orchestrator mode). QA always; specialist when asked."""
        personas = ["qa"]
        intent = classify_intent(question)
        if intent == "dev_search" and not self.deps.settings.dev_search_enabled:
            intent = "qa"
        if intent != "qa":
            personas.append(intent)
        return personas

    async def _run_persona(
        self, persona: str, repo_id: str, question: str, repo_name: str | None
    ) -> Answer:
        graph = self._graph_for(persona)
        state = QueryState(repo_id=repo_id, question=question, repo_name=repo_name)
        result = await graph.ainvoke(state, config={"recursion_limit": RECURSION_LIMIT})
        ans = result.get("answer") if isinstance(result, dict) else None
        return ans or Answer(text="No answer produced.", refused=True, refusal_reason="empty")

    async def _orchestrate(
        self, repo_id: str, question: str, repo_name: str | None
    ) -> tuple[list[str], Answer]:
        """Crisis-check, then fan out to the selected personas in parallel and merge."""
        if should_escalate(question, threshold=self.deps.settings.escalation_threshold):
            return ["help"], escalation_answer()
        personas = self._select_personas(question)
        answers = await asyncio.gather(
            *[self._run_persona(p, repo_id, question, repo_name) for p in personas]
        )
        return personas, merge_answers(list(zip(personas, answers, strict=True)))

    async def run(self, repo_id: str, question: str, repo_name: str | None = None) -> Answer:
        timeout = self.deps.settings.request_timeout_s
        if self.deps.settings.orchestrator_enabled:
            async with asyncio.timeout(timeout):
                _personas, orchestrated = await self._orchestrate(repo_id, question, repo_name)
            return orchestrated
        state = QueryState(repo_id=repo_id, question=question, repo_name=repo_name)
        graph, _intent = self._route(question)
        async with asyncio.timeout(timeout):
            result = await graph.ainvoke(state, config={"recursion_limit": RECURSION_LIMIT})
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
        answer: Answer | None = None
        if self.deps.settings.orchestrator_enabled:
            async with asyncio.timeout(self.deps.settings.request_timeout_s):
                personas, answer = await self._orchestrate(repo_id, question, repo_name)
            for p in personas:
                yield {"type": "persona_active", "persona": p}
            if personas == ["help"]:
                yield {"type": "escalation", "mode": "human"}
        else:
            state = QueryState(repo_id=repo_id, question=question, repo_name=repo_name)
            graph, intent = self._route(question)
            if intent != "qa":
                yield {"type": "route", "persona": intent}
            async with asyncio.timeout(self.deps.settings.request_timeout_s):
                async for chunk in graph.astream(
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
    if node == "locate_targets":
        n = len(update.get("target_paths") or [])
        return {"type": "status", "label": "Locating the file(s)", "detail": f"{n} file(s)"}
    if node == "authorship_lookup":
        n = len(update.get("authorship") or [])
        return {"type": "status", "label": "Looking up git authorship", "detail": f"{n} file(s)"}
    if node == "assemble_authorship":
        return {"type": "status", "label": "Reading authorship history"}
    if node == "grounding_check":
        if update.get("answer") is not None:
            return {"type": "status", "label": "Verifying attribution against git"}
        return {"type": "status", "label": "Refining — an author wasn't in the git records"}
    if node == "authorship_refuse":
        return {"type": "status", "label": "No authorship history for this file"}
    return None
