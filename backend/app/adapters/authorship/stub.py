"""Disabled authorship adapter — used when dev-search is off (mirrors the graph-store stub)."""

from __future__ import annotations

from app.domain.models import BlameSpan, FileAuthorship, RepoContext


class StubAuthorship:
    @property
    def enabled(self) -> bool:
        return False

    async def file_authorship(self, ctx: RepoContext, path: str) -> FileAuthorship | None:
        return None

    async def blame_range(
        self, ctx: RepoContext, path: str, start: int, end: int
    ) -> list[BlameSpan]:
        return []
