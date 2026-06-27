"""Typed state + dependency bundle for the query graph (harness component 1).

State is a pydantic model so each node is a near-pure `State -> partial State` function,
unit-testable in isolation. Deps carries the ports the nodes call, so tests can inject fakes
(and the critic loop / budgets stay explicit in state).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.domain.models import Answer, Hit, SparseVector
from app.domain.retrieval.context import Source
from app.ports.embedder import Embedder
from app.ports.generator import Generator
from app.ports.graph_store import GraphStore
from app.ports.sparse_embedder import SparseEmbedder
from app.ports.vector_store import VectorStore


class QueryState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo_id: str
    repo_name: str | None = None
    question: str

    dense: list[float] = []
    sparse: SparseVector | None = None
    fused: list[Hit] = []
    ranked: list[Hit] = []
    sources: list[Source] = []
    sources_block: str = ""

    draft: str = ""
    best_draft: str = ""  # earliest validly-cited draft, kept as a fallback at exhaustion
    critic_iters: int = 0
    feedback: str = ""

    answer: Answer | None = None


@dataclass
class Deps:
    embedder: Embedder
    sparse: SparseEmbedder
    vectors: VectorStore
    generator: Generator
    graph_store: GraphStore
    settings: Settings
