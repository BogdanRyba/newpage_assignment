"""The dev-search persona graph — "who wrote / last changed this code?".

    embed → retrieve → [scope_refuse | rerank → locate_targets → authorship_lookup
        → [authorship_refuse | assemble → assemble_authorship → generate → grounding_check]]
    grounding_check → generate (retry on a bad attribution) | END

Reuses the QA retrieval/assemble nodes; the new nodes locate target files, fetch real git
authorship, and ground every attribution against it. Bounded by max_critic_iterations.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.services.query.nodes.critic import scope_refuse_node
from app.services.query.nodes.dev_search import (
    assemble_authorship_node,
    authorship_lookup_node,
    authorship_refuse_node,
    generate_dev_node,
    grounding_check_node,
    locate_targets_node,
)
from app.services.query.nodes.retrieval import embed_node, rerank_node, retrieve_node
from app.services.query.nodes.synthesis import assemble_node
from app.services.query.state import Deps, QueryState


def _after_retrieve(state: QueryState) -> str:
    return "scope_refuse" if not state.fused else "rerank"


def _after_authorship(state: QueryState) -> str:
    return "assemble" if state.authorship else "authorship_refuse"


def _after_grounding(state: QueryState) -> str:
    return "end" if state.answer is not None else "generate"


def build_dev_search_graph(deps: Deps):  # noqa: ANN201 — compiled LangGraph
    g = StateGraph(QueryState)
    nodes = {
        "embed": embed_node(deps),
        "retrieve": retrieve_node(deps),
        "rerank": rerank_node(deps),
        "locate_targets": locate_targets_node(deps),
        "authorship_lookup": authorship_lookup_node(deps),
        "authorship_refuse": authorship_refuse_node(deps),
        "assemble": assemble_node(deps),
        "assemble_authorship": assemble_authorship_node(deps),
        "generate": generate_dev_node(deps),
        "grounding_check": grounding_check_node(deps),
        "scope_refuse": scope_refuse_node(deps),
    }
    for name, fn in nodes.items():
        g.add_node(name, fn)  # type: ignore[call-overload]

    g.add_edge(START, "embed")
    g.add_edge("embed", "retrieve")
    g.add_conditional_edges(
        "retrieve", _after_retrieve, {"scope_refuse": "scope_refuse", "rerank": "rerank"}
    )
    g.add_edge("rerank", "locate_targets")
    g.add_edge("locate_targets", "authorship_lookup")
    g.add_conditional_edges(
        "authorship_lookup",
        _after_authorship,
        {"assemble": "assemble", "authorship_refuse": "authorship_refuse"},
    )
    g.add_edge("assemble", "assemble_authorship")
    g.add_edge("assemble_authorship", "generate")
    g.add_edge("generate", "grounding_check")
    g.add_conditional_edges(
        "grounding_check", _after_grounding, {"generate": "generate", "end": END}
    )
    g.add_edge("scope_refuse", END)
    g.add_edge("authorship_refuse", END)
    return g.compile()
