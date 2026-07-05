"""Seeder: idempotently ingest the bundled sample repo so the demo works immediately.

Runs the ingest pipeline inline (no worker needed) against `sample_repo/`. Skips if a
ready "sample" repo already exists. When no Gemini key is configured, falls back to the
offline demo path (local embedder + cassette replay) so `docker compose up` works out of
the box.
"""

from __future__ import annotations

import asyncio
import os
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


def ensure_demo_credentials() -> None:
    """Fall back to offline demo mode when Gemini is selected but no key is set."""
    if os.getenv("EMBEDDING_PROVIDER", "gemini") == "gemini" and not os.getenv("GEMINI_API_KEY"):
        os.environ["EMBEDDING_PROVIDER"] = "local"
        if os.getenv("CASSETTE_MODE", "off") == "off":
            os.environ["CASSETTE_MODE"] = "replay"
        get_settings.cache_clear()


async def main() -> None:
    ensure_demo_credentials()
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
