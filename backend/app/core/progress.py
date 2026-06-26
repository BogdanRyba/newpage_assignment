"""Ingest progress over Redis pub/sub.

The worker publishes phase/percent events; the API's SSE endpoint subscribes and forwards
them to the Indexing screen. Decoupling via Redis means the API process never blocks on the
worker and survives worker restarts.
"""

from __future__ import annotations

import json

import redis.asyncio as redis

from app.core.config import get_settings


def channel(repo_id: str) -> str:
    return f"ingest:{repo_id}"


async def publish(repo_id: str, event: dict) -> None:
    client = redis.from_url(get_settings().redis_url)
    try:
        await client.publish(channel(repo_id), json.dumps(event))
    finally:
        await client.aclose()
