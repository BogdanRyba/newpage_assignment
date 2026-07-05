"""Domain value objects — pure data, no framework/infra/LangChain imports.

These types are the contracts that flow between pipeline stages (chunk → embed →
index; retrieve → fuse → rerank → generate → cite). Keeping them framework-free is
the one piece of DDD we deliberately borrow: the core logic never depends on how
things are stored or served.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field


class RepoContext(BaseModel, frozen=True):
    """Carries multi-repo scope through every stage and adapter.

    Isolation is explicit, not accidental: the Qdrant collection and the graph
    namespace are derived from ``repo_id`` so no query can leak across repos.
    """

    repo_id: str
    name: str = ""

    @property
    def qdrant_collection(self) -> str:
        return f"repo_{self.repo_id}"

    @property
    def graph_namespace(self) -> str:
        return self.repo_id


class CodeLocation(BaseModel, frozen=True):
    """A path + inclusive 1-based line range. The unit every citation points at."""

    path: str
    start_line: int
    end_line: int

    @property
    def label(self) -> str:
        if self.start_line == self.end_line:
            return f"{self.path}:{self.start_line}"
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def contains(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line


class Chunk(BaseModel):
    """One retrievable unit of code. Mirrors the Postgres `chunks` row + Qdrant payload."""

    repo_id: str
    path: str
    blob_sha: str = ""  # git blob OID — the content address; identical content shares it
    lang: str
    symbol: str | None
    kind: str
    start_line: int
    end_line: int
    text: str
    index: int = 0
    bases: list[str] = Field(default_factory=list)  # superclasses / super-interfaces (extends)
    implements: list[str] = Field(default_factory=list)  # interfaces a class implements (TS)

    @property
    def location(self) -> CodeLocation:
        return CodeLocation(path=self.path, start_line=self.start_line, end_line=self.end_line)

    @property
    def point_id(self) -> str:
        """Deterministic id → re-ingestion upserts in place, never duplicates.

        Keyed by blob content (not path), so identical content across branches/versions
        — or moved to a new path — maps to the SAME points and is never re-embedded.
        """
        return point_id(self.repo_id, self.blob_sha, self.index)


class Hit(BaseModel):
    """A retrieved chunk with a relevance score and its provenance."""

    chunk: Chunk
    score: float
    source: str = "fused"  # dense | sparse | fused | rerank | graph


class Citation(BaseModel):
    """A validated reference from an answer back to source lines."""

    n: int
    location: CodeLocation
    symbol: str | None = None


class Answer(BaseModel):
    """The terminal output of the query graph."""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None


def point_id(repo_id: str, blob_sha: str, index: int) -> str:
    """uuid5(repo_id:blob_sha:index) — content-addressed → idempotent + shared.

    Unchanged blobs across versions/branches reuse the same id (never re-embedded);
    a re-ingest of identical content upserts in place. ``repo_id`` keeps it scoped so
    no point can leak across repos.
    """
    return str(uuid5(NAMESPACE_URL, f"{repo_id}:{blob_sha}:{index}"))


class CommitRef(BaseModel, frozen=True):
    """One commit that touched a file — the unit of authorship history.

    Author/email/subject are attacker-controllable repo data: sanitize + fence before they
    reach any prompt, and attribute only to values present in these structured records.
    """

    sha: str
    author: str
    email: str = ""
    committed_at: str = ""  # ISO-8601
    subject: str = ""


class FileAuthorship(BaseModel, frozen=True):
    """Who last changed a file + its recent commit history (the dev-search answer unit)."""

    path: str
    last_author: str
    last_author_email: str = ""
    last_commit_sha: str = ""
    last_commit_at: str = ""
    recent_commits: list[CommitRef] = Field(default_factory=list)


class BlameSpan(BaseModel, frozen=True):
    """Authorship of a contiguous line range (on-demand `git blame`)."""

    start_line: int
    end_line: int
    author: str
    commit_sha: str = ""
    committed_at: str = ""


class SparseVector(BaseModel):
    """A sparse lexical vector (term index → weight). Produced by the sparse embedder."""

    indices: list[int]
    values: list[float]


class VectorPoint(BaseModel):
    """One row to upsert into Qdrant: id + named dense/sparse vectors + payload."""

    id: str
    dense: list[float]
    sparse: SparseVector
    payload: dict


class ScoredPoint(BaseModel):
    """A search result from the vector store: point id, score, and stored payload."""

    id: str
    score: float
    payload: dict


class GraphNode(BaseModel):
    """A code symbol in the graph store. Self-contained (carries its text) so graph
    augmentation needs no extra DB lookup."""

    symbol: str
    path: str
    lang: str
    kind: str
    start_line: int
    end_line: int
    text: str
    point_id: str


class GraphEdge(BaseModel):
    """A directed relationship between two symbols (by name) within a repo.

    `src_lang` scopes the edge to one language so two same-named symbols in different
    languages (e.g. a Python and a TS `Ranker`) never cross-link at upsert time.
    """

    src: str  # source symbol name
    dst: str  # destination symbol name
    type: str  # CALLS | CONTAINS | EXTENDS | IMPLEMENTS
    src_lang: str = ""  # language of the source symbol (edges only connect same-language nodes)
