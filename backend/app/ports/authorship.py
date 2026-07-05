"""Port: code authorship lookup (who/when changed a file).

A volatile IO boundary like the other ports. The default adapter reads authorship captured
into Postgres at ingest; line-level `git blame` is on-demand and may be a no-op when no
persisted checkout is available. Disabled adapter (`enabled=False`) is the stub.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import BlameSpan, FileAuthorship, RepoContext


@runtime_checkable
class AuthorshipPort(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def file_authorship(self, ctx: RepoContext, path: str) -> FileAuthorship | None:
        """Last author + recent commit history for a file, or None if unknown."""
        ...

    async def blame_range(
        self, ctx: RepoContext, path: str, start: int, end: int
    ) -> list[BlameSpan]:
        """Per-line authorship for a range; may be empty when unavailable."""
        ...
