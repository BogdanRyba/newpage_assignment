"""Taskiq broker + ingest task entrypoint.

The broker lives here so the worker can boot in Phase 0. The real ingest pipeline
(clone → walk → parse → chunk → embed → index) is wired in Phase 1; it is an
*idempotent* job — safe to retry because point IDs are deterministic (uuid5).
"""

from __future__ import annotations

from taskiq_redis import ListQueueBroker

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger("worker")

broker = ListQueueBroker(settings.redis_url)


@broker.task
async def ping() -> str:
    """Smoke task so the worker has something to import and run."""
    log.info("ping")
    return "pong"


@broker.task
async def ingest_repo(
    repo_id: str,
    job_id: str,
    source_url: str | None = None,
    local_path: str | None = None,
    has_upload: bool = False,
) -> None:
    """Run the full ingest pipeline for a repo. Idempotent (uuid5 point IDs)."""
    from app.core.uploads import pop_upload
    from app.db.session import SessionLocal
    from app.services.ingest_service import IngestService

    zip_bytes = await pop_upload(job_id) if has_upload else None
    async with SessionLocal() as session:
        await IngestService(session).run(
            repo_id=repo_id,
            job_id=job_id,
            source_url=source_url,
            zip_bytes=zip_bytes,
            local_path=local_path,
        )
