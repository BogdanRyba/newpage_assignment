"""DI factory — builds the right adapter for each port from config.

The one place that knows which concrete implementation backs each volatile boundary.
Heavy/stateful adapters (vector client, sparse model, parser) are cached as singletons.
"""

from __future__ import annotations

from functools import lru_cache

from app.adapters.embedding.gemini import GeminiEmbedder
from app.adapters.embedding.sparse_fastembed import FastEmbedSparse
from app.adapters.embedding.voyage import VoyageEmbedder
from app.adapters.graph.neo4j import Neo4jGraphStoreStub
from app.adapters.parsing.tree_sitter import TreeSitterParser
from app.adapters.vector.qdrant import QdrantVectorStore
from app.core.config import get_settings
from app.ports.embedder import Embedder
from app.ports.graph_store import GraphStore
from app.ports.parser import Parser
from app.ports.sparse_embedder import SparseEmbedder
from app.ports.vector_store import VectorStore


@lru_cache
def make_parser() -> Parser:
    return TreeSitterParser()


@lru_cache
def make_embedder() -> Embedder:
    provider = get_settings().embedding_provider
    if provider == "voyage":
        return VoyageEmbedder()
    if provider == "local":
        from app.adapters.embedding.local import LocalHashEmbedder

        return LocalHashEmbedder()
    return GeminiEmbedder()


@lru_cache
def make_sparse_embedder() -> SparseEmbedder:
    # The local provider keeps the whole pipeline offline/deterministic (CI, no-key demo).
    if get_settings().embedding_provider == "local":
        from app.adapters.embedding.local import LocalHashSparse

        return LocalHashSparse()
    return FastEmbedSparse()


@lru_cache
def make_vector_store() -> VectorStore:
    return QdrantVectorStore()


@lru_cache
def make_graph_store() -> GraphStore:
    return Neo4jGraphStoreStub()
