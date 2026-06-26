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
