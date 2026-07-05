"""SQLAlchemy ORM models — the persistent state for repos, ingest jobs, files,
chunks, chat, and evals. Vectors live in Qdrant; full file content lives here so the
UI's source panel can be served directly.

Imported by Alembic's env so every table registers on the shared metadata.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

__all__ = ["Base"]


def _uuid() -> str:
    return uuid4().hex


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), default="pending"
    )  # pending|indexing|ready|failed
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    # True for repos indexed under the legacy path-based point_id scheme: their Qdrant
    # points cannot be matched under the blob-addressed scheme, so they need a one-time
    # re-ingest (first-ingest, parent=None). The migration flags existing ready repos.
    needs_reingest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files: Mapped[list[File]] = relationship(back_populates="repo", cascade="all, delete-orphan")
    versions: Mapped[list[RepoVersion]] = relationship(
        back_populates="repo", cascade="all, delete-orphan"
    )


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued|running|done|failed
    phase: Mapped[str] = mapped_column(String(32), default="cloning")
    files_done: Mapped[int] = mapped_column(Integer, default=0)
    chunks_done: Mapped[int] = mapped_column(Integer, default=0)
    pct: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class File(Base):
    __tablename__ = "files"
    # Content-addressed: one row per distinct (repo, blob), shared across versions/paths.
    __table_args__ = (UniqueConstraint("repo_id", "blob_sha", name="uq_files_repo_blob"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    # Git blob OID — the content address. Nullable during the transition; once the
    # content-addressed ingest lands, every file row carries one and (repo_id, blob_sha)
    # becomes unique. Identical content (same blob) is shared across versions/paths.
    blob_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    lang: Mapped[str] = mapped_column(String(32), default="text")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)  # extracted/decoded text (chunked + served)
    # Original bytes, only for binary docs we render visually (PDFs). NULL for source files.
    raw: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Authorship captured from git at ingest (powers dev-search). NULL for non-git uploads.
    last_author: Mapped[str | None] = mapped_column(String(255))
    last_author_email: Mapped[str | None] = mapped_column(String(255))
    last_commit_sha: Mapped[str | None] = mapped_column(String(64))
    last_commit_at: Mapped[str | None] = mapped_column(String(40))
    commit_history: Mapped[list | None] = mapped_column(JSON)  # recent CommitRefs (dicts)

    repo: Mapped[Repo] = relationship(back_populates="files")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="file", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    # Chunk index within its file/blob — the third input to the blob-addressed point_id.
    # Chunks for a given immutable blob are write-once, so (file_id, index) is stable.
    index: Mapped[int] = mapped_column(Integer, default=0)
    qdrant_point_id: Mapped[str] = mapped_column(String(64), index=True)

    file: Mapped[File] = relationship(back_populates="chunks")


class RepoVersion(Base):
    """One indexed snapshot of a repo at a specific commit (a branch tip, tag, or
    detached commit). A branch ref moves over time, so re-indexing ``main`` at a new
    commit creates a NEW row — old versions stay for history and comparison.
    ``UNIQUE(repo_id, commit_sha)`` is the no-op gate: the same commit is never
    re-indexed twice.
    """

    __tablename__ = "repo_versions"
    __table_args__ = (
        UniqueConstraint("repo_id", "commit_sha", name="uq_repo_versions_repo_commit"),
        Index("ix_repo_versions_repo_ref", "repo_id", "ref_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    ref_name: Mapped[str] = mapped_column(String(255))  # "main", "dev", "v2.3.5", or a raw sha
    ref_type: Mapped[str] = mapped_column(String(16), default="branch")  # branch|tag|commit
    commit_sha: Mapped[str] = mapped_column(String(64))  # full 40-char OID
    # Nearest already-indexed ancestor this version was incrementally built from.
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("repo_versions.id", ondelete="SET NULL")
    )
    # pending|indexing|ready|failed
    status: Mapped[str] = mapped_column(String(32), default="pending")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repo: Mapped[Repo] = relationship(back_populates="versions")
    files: Mapped[list[VersionFile]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class VersionFile(Base):
    """The manifest: which blob sits at which path in a given version.

    Joined to ``files.blob_sha`` it IS the path→blob map. ``ON DELETE RESTRICT`` on
    ``file_id`` is the set-membership refcount — a blob (file row) cannot be dropped
    while any version still references it. GC reclaims only blobs with zero rows here.
    """

    __tablename__ = "version_files"
    __table_args__ = (
        Index("ix_version_files_file", "file_id"),
    )

    version_id: Mapped[str] = mapped_column(
        ForeignKey("repo_versions.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"))

    version: Mapped[RepoVersion] = relationship(back_populates="files")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metrics_json: Mapped[dict | None] = mapped_column(JSON)


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    question: Mapped[str] = mapped_column(Text)
    expected_files_json: Mapped[list | None] = mapped_column(JSON)
    expected_symbols_json: Mapped[list | None] = mapped_column(JSON)
    expect_refusal: Mapped[bool] = mapped_column(default=False)
