"""Seeder: idempotently ingest the bundled sample repo so the demo works immediately.

Runs the ingest pipeline inline (no worker needed) against `sample_repo/`. Skips if a
ready "sample" repo already exists, or if no embedding key is configured (the app needs a
Gemini key to function — without it we skip rather than fail noisily).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Repo
from app.db.repositories.ingest_jobs import IngestJobRepository
from app.db.repositories.repos import RepoRepository
from app.db.session import SessionLocal
from app.services.ingest_service import IngestService

log = get_logger("seed")
SAMPLE_PATH = Path(__file__).resolve().parents[2] / "sample_repo"
SAMPLE_NAME = "notes-service"


async def main() -> None:
    settings = get_settings()
    if settings.embedding_provider == "gemini" and not settings.gemini_api_key:
        log.info("seed_skipped", reason="no GEMINI_API_KEY set — set it in .env to seed the demo")
        return
    if not SAMPLE_PATH.exists():
        log.info("seed_skipped", reason=f"sample repo not found at {SAMPLE_PATH}")
        return

    async with SessionLocal() as session:
        existing = await session.scalar(
            select(Repo).where(Repo.name == SAMPLE_NAME, Repo.status == "ready")
        )
        if existing:
            log.info("seed_skipped", reason="sample already ingested", repo_id=existing.id)
            return

        repos, jobs = RepoRepository(session), IngestJobRepository(session)
        repo = await repos.create(name=SAMPLE_NAME, source_url=None)
        job = await jobs.create(repo.id)
        log.info("seed_start", repo_id=repo.id, path=str(SAMPLE_PATH))
        await IngestService(session).run(
            repo_id=repo.id, job_id=job.id, local_path=str(SAMPLE_PATH)
        )
        log.info("seed_done", repo_id=repo.id)


if __name__ == "__main__":
    asyncio.run(main())
