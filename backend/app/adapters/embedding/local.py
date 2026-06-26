"""Deterministic, offline embedders (EMBEDDING_PROVIDER=local).

No API key, no network, no model download — hashed bag-of-tokens vectors. They're not
as good as Gemini/Voyage, but they're *deterministic*, which makes the full ingest +
retrieval pipeline runnable in CI and demoable with zero credentials. Cosine similarity
here approximates lexical overlap, which is enough for tests that assert a query retrieves
the chunk containing a shared symbol.
"""

from __future__ import annotations

import math
import re

from app.domain.models import SparseVector

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DENSE_DIM = 256
SPARSE_VOCAB = 1 << 20


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _hash(token: str, mod: int) -> int:
    h = 2166136261
    for ch in token:
        h = (h ^ ord(ch)) * 16777619 & 0xFFFFFFFF
    return h % mod


class LocalHashEmbedder:
    def __init__(self, dim: int = DENSE_DIM) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int | None:
        return self._dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        for tok in _tokens(text):
            v[_hash(tok, self._dim)] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class LocalHashSparse:
    def __init__(self, vocab: int = SPARSE_VOCAB) -> None:
        self._vocab = vocab

    def _sparse(self, text: str) -> SparseVector:
        counts: dict[int, float] = {}
        for tok in _tokens(text):
            counts[_hash(tok, self._vocab)] = counts.get(_hash(tok, self._vocab), 0.0) + 1.0
        items = sorted(counts.items())
        return SparseVector(indices=[i for i, _ in items], values=[v for _, v in items])

    async def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [self._sparse(t) for t in texts]

    async def embed_query(self, text: str) -> SparseVector:
        return self._sparse(text)
