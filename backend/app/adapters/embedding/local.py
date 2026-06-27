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
# Split an identifier into subwords: camelCase, snake_case, digits.
_SUBWORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
DENSE_DIM = 256
SPARSE_VOCAB = 1 << 20
# The contextual header (`# path · symbol`, prepended by chunking's with_context) names the
# symbol a chunk defines and its file — the highest-signal tokens for "how does X work?" /
# "the web layer" queries. Boost them so a distinctive symbol/file token outweighs the common
# body tokens (note, search, self, return) that otherwise drown it out in a plain bag-of-tokens.
# This is the lexical stand-in for what a semantic embedder does; real Gemini needs no such hint.
HEADER_BOOST = 4.0


def _tokens(text: str) -> list[str]:
    # Emit the whole identifier AND its subwords so "create note" matches `createNote`
    # and "max results" matches `MAX_RESULTS` — closing the lexical gap of bag-of-tokens.
    out: list[str] = []
    for ident in _TOKEN.findall(text):
        out.append(ident.lower())
        for part in ident.split("_"):
            out.extend(sub.lower() for sub in _SUBWORD.findall(part))
    return out


def _weighted_tokens(text: str) -> list[tuple[str, float]]:
    """Tokens with weights. A leading `# …` context line (the chunk's path · symbol header) is
    weighted HEADER_BOOST; body tokens weigh 1.0. Queries carry no header, so every query token
    weighs 1.0 — the boost only sharpens *documents* toward the symbol/file they're about."""
    header, sep, body = text.partition("\n")
    if header.startswith("# "):
        weighted = [(tok, HEADER_BOOST) for tok in _tokens(header)]
        weighted += [(tok, 1.0) for tok in _tokens(body)]
        return weighted
    return [(tok, 1.0) for tok in _tokens(text)]


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
        for tok, weight in _weighted_tokens(text):
            v[_hash(tok, self._dim)] += weight
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
        for tok, weight in _weighted_tokens(text):
            idx = _hash(tok, self._vocab)
            counts[idx] = counts.get(idx, 0.0) + weight
        items = sorted(counts.items())
        return SparseVector(indices=[i for i, _ in items], values=[v for _, v in items])

    async def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [self._sparse(t) for t in texts]

    async def embed_query(self, text: str) -> SparseVector:
        return self._sparse(text)
