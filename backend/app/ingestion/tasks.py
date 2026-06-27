"""Taskiq broker + ingest task entrypoint.

The broker lives here so the worker can boot in Phase 0. The real ingest pipeline
(clone → walk → parse → chunk → embed → index) is wired in Phase 1; it is an
*idempotent* job — safe to retry because point IDs are deterministic (uuid5).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from redis.exceptions import TimeoutError as RedisTimeoutError
from taskiq_redis import ListQueueBroker

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger("worker")


class ResilientListQueueBroker(ListQueueBroker):
    """A ListQueueBroker whose listen loop survives an idle BRPOP read-timeout.

    Upstream `listen()` retries on `ConnectionError` but lets redis-py's `TimeoutError`
    (raised when a blocking BRPOP exceeds the socket read timeout on an idle queue) propagate —
    which kills the worker process. That turns every idle period into a crash loop and interrupts
    long-running ingest tasks (clone → embed) mid-flight, so URL ingests never finish. A timeout
    on an *idle* pop is benign: log it and keep listening, just like the ConnectionError path.
    """

    async def listen(self) -> AsyncGenerator[bytes, None]:
        while True:
            try:
                async for message in super().listen():
                    yield message
            except (RedisTimeoutError, TimeoutError) as exc:  # idle BRPOP read-timeout — benign
                log.debug("broker_idle_timeout", error=str(exc))
                continue


broker = ResilientListQueueBroker(settings.redis_url)


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
