"""The query graph — Daedalus. A LangGraph StateGraph wiring the pipeline + critic loop.

    embed → retrieve → [scope_refuse | rerank → graph_augment → assemble → generate → critic]
    critic → generate (retry with feedback)  |  END (answer set)

The loop is bounded by `max_critic_iterations` (in the critic) and `recursion_limit` (at invoke).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.services.query.nodes.critic import critic_node, scope_refuse_node
from app.services.query.nodes.retrieval import (
    embed_node,
    graph_augment_node,
    rerank_node,
    retrieve_node,
)
from app.services.query.nodes.synthesis import assemble_node, generate_node
from app.services.query.state import Deps, QueryState


def _after_retrieve(state: QueryState) -> str:
    return "scope_refuse" if not state.fused else "rerank"


def _after_critic(state: QueryState) -> str:
    return "end" if state.answer is not None else "generate"


def build_graph(deps: Deps):  # noqa: ANN201 — returns a compiled LangGraph
    g = StateGraph(QueryState)
    nodes = {
        "embed": embed_node(deps),
        "retrieve": retrieve_node(deps),
        "rerank": rerank_node(deps),
        "graph_augment": graph_augment_node(deps),
        "assemble": assemble_node(deps),
        "generate": generate_node(deps),
        "critic": critic_node(deps),
        "scope_refuse": scope_refuse_node(deps),
    }
    for name, fn in nodes.items():
        g.add_node(name, fn)  # type: ignore[call-overload]  # node returns a partial-state dict

    g.add_edge(START, "embed")
    g.add_edge("embed", "retrieve")
    g.add_conditional_edges(
        "retrieve", _after_retrieve, {"scope_refuse": "scope_refuse", "rerank": "rerank"}
    )
    g.add_edge("rerank", "graph_augment")
    g.add_edge("graph_augment", "assemble")
    g.add_edge("assemble", "generate")
    g.add_edge("generate", "critic")
    g.add_conditional_edges("critic", _after_critic, {"generate": "generate", "end": END})
    g.add_edge("scope_refuse", END)
    return g.compile()
