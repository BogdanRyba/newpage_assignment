"""Synthesis-side nodes: assemble context, generate a cited draft."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.instrument import instrument
from app.domain.retrieval.context import assemble
from app.prompts import synthesis
from app.services.query.state import Deps, QueryState

Node = Callable[[QueryState], Awaitable[dict]]


def assemble_node(deps: Deps) -> Node:
    @instrument("assemble_context")
    async def _node(state: QueryState) -> dict:
        sources, block = assemble(state.ranked, token_budget=deps.settings.token_budget)
        return {"sources": sources, "sources_block": block}

    return _node


def generate_node(deps: Deps) -> Node:
    @instrument("generate")
    async def _node(state: QueryState) -> dict:
        user = synthesis.build_user(
            state.question, state.sources_block, feedback=state.feedback or None
        )
        draft = await deps.generator.complete(synthesis.SYSTEM, user)
        return {"draft": draft.strip()}

    return _node


def generate_research_node(deps: Deps) -> Node:
    """Like generate_node but with the research prompt (structural relationships)."""
    from app.prompts import research

    @instrument("generate")
    async def _node(state: QueryState) -> dict:
        user = research.build_user(
            state.question, state.sources_block, feedback=state.feedback or None
        )
        draft = await deps.generator.complete(research.SYSTEM, user)
        return {"draft": draft.strip()}

    return _node


def generate_architect_node(deps: Deps) -> Node:
    """Like generate_node but with the architect prompt (structure/patterns/design)."""
    from app.prompts import architect

    @instrument("generate")
    async def _node(state: QueryState) -> dict:
        user = architect.build_user(
            state.question, state.sources_block, feedback=state.feedback or None
        )
        draft = await deps.generator.complete(architect.SYSTEM, user)
        return {"draft": draft.strip()}

    return _node
