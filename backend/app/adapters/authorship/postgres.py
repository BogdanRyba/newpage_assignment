"""Authorship adapter backed by Postgres (data captured at ingest).

Reads the per-file authorship columns the ingest pipeline fills from git. Self-contained:
opens its own session (like the chat persistence path) so it needs no request session.
Line-level blame is not persisted (clones are ephemeral), so `blame_range` returns []
for now — the dev-search agent attributes at file granularity, never fabricating lines.
"""

from __future__ import annotations

from app.db.repositories.files import FileRepository
from app.db.session import SessionLocal
from app.domain.models import BlameSpan, CommitRef, FileAuthorship, RepoContext


class PostgresAuthorship:
    @property
    def enabled(self) -> bool:
        return True

    async def file_authorship(self, ctx: RepoContext, path: str) -> FileAuthorship | None:
        async with SessionLocal() as session:
            f = await FileRepository(session).get_by_path(ctx.repo_id, path)
        if f is None or not f.last_author:
            return None
        recent = [CommitRef(**c) for c in (f.commit_history or []) if isinstance(c, dict)]
        return FileAuthorship(
            path=path,
            last_author=f.last_author,
            last_author_email=f.last_author_email or "",
            last_commit_sha=f.last_commit_sha or "",
            last_commit_at=f.last_commit_at or "",
            recent_commits=recent,
        )

    async def blame_range(
        self, ctx: RepoContext, path: str, start: int, end: int
    ) -> list[BlameSpan]:
        return []  # per-line blame requires a persisted checkout; file-level is the signal
