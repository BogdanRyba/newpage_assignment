"""SQLAlchemy ORM models.

Tables are added in Phase 1 (repos, ingest_jobs, files, chunks, chat_sessions,
messages, eval_runs, eval_cases). This module is imported by Alembic's env so
all tables register on the shared metadata.
"""

from __future__ import annotations

from app.db.base import Base

__all__ = ["Base"]
