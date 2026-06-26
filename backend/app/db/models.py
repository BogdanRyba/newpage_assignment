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
    DateTime,
    ForeignKey,
    Integer,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files: Mapped[list[File]] = relationship(back_populates="repo", cascade="all, delete-orphan")


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
    __table_args__ = (UniqueConstraint("repo_id", "path", name="uq_files_repo_path"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    lang: Mapped[str] = mapped_column(String(32), default="text")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)

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
    qdrant_point_id: Mapped[str] = mapped_column(String(64), index=True)

    file: Mapped[File] = relationship(back_populates="chunks")


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
