"""Repository for `repos`. DB access for repositories lives here, never in endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Repo


class RepoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, name: str, source_url: str | None) -> Repo:
        repo = Repo(name=name, source_url=source_url, status="pending")
        self.session.add(repo)
        await self.session.commit()
        await self.session.refresh(repo)
        return repo

    async def get(self, repo_id: str) -> Repo | None:
        return await self.session.get(Repo, repo_id)

    async def list(self) -> list[Repo]:
        result = await self.session.execute(select(Repo).order_by(Repo.created_at.desc()))
        return list(result.scalars().all())

    async def set_status(self, repo_id: str, status: str) -> None:
        repo = await self.session.get(Repo, repo_id)
        if repo:
            repo.status = status
            await self.session.commit()

    async def finalize(
        self, repo_id: str, *, commit_sha: str | None, file_count: int, chunk_count: int
    ) -> None:
        repo = await self.session.get(Repo, repo_id)
        if repo:
            repo.status = "ready"
            repo.commit_sha = commit_sha
            repo.file_count = file_count
            repo.chunk_count = chunk_count
            repo.ingested_at = datetime.now(UTC)
            await self.session.commit()
