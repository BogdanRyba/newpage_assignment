"""Repository for `ingest_jobs` — drives the Indexing screen's phase/progress."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestJob


class IngestJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_for_repo(self, repo_id: str) -> IngestJob | None:
        return await self.session.scalar(
            select(IngestJob)
            .where(IngestJob.repo_id == repo_id)
            .order_by(IngestJob.created_at.desc())
            .limit(1)
        )

    async def create(self, repo_id: str) -> IngestJob:
        job = IngestJob(repo_id=repo_id, status="queued", phase="cloning")
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get(self, job_id: str) -> IngestJob | None:
        return await self.session.get(IngestJob, job_id)

    async def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        files_done: int | None = None,
        chunks_done: int | None = None,
        pct: int | None = None,
        error: str | None = None,
    ) -> None:
        job = await self.session.get(IngestJob, job_id)
        if not job:
            return
        if status is not None:
            job.status = status
        if phase is not None:
            job.phase = phase
        if files_done is not None:
            job.files_done = files_done
        if chunks_done is not None:
            job.chunks_done = chunks_done
        if pct is not None:
            job.pct = pct
        if error is not None:
            job.error = error
        await self.session.commit()
