"""Hand an uploaded .zip from the API to the worker via Redis.

api and worker are separate containers with no shared filesystem, so the upload bytes
are stashed in Redis under the job id (short TTL) and popped by the worker.
"""

from __future__ import annotations

import redis.asyncio as redis

from app.core.config import get_settings

TTL_SECONDS = 3600


def _key(job_id: str) -> str:
    return f"upload:{job_id}"


async def store_upload(job_id: str, data: bytes) -> None:
    client = redis.from_url(get_settings().redis_url)
    try:
        await client.set(_key(job_id), data, ex=TTL_SECONDS)
    finally:
        await client.aclose()


async def pop_upload(job_id: str) -> bytes | None:
    client = redis.from_url(get_settings().redis_url)
    try:
        data = await client.get(_key(job_id))
        if data is None:
            return None
        await client.delete(_key(job_id))
        return data if isinstance(data, bytes) else str(data).encode("utf-8")
    finally:
        await client.aclose()
