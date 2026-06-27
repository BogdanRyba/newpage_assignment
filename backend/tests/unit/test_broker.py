"""The ingest broker must survive an idle BRPOP read-timeout, not crash the worker.

Regression: taskiq_redis's listen() retries on ConnectionError but lets redis-py TimeoutError
propagate, killing the worker (crash loop → URL ingests never finish). Our broker retries on
timeouts too — while still surfacing genuine errors.
"""

from __future__ import annotations

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError
from taskiq_redis import ListQueueBroker

from app.ingestion.tasks import ResilientListQueueBroker


@pytest.mark.parametrize("timeout_exc", [RedisTimeoutError("idle pop"), TimeoutError("idle pop")])
async def test_listen_retries_after_idle_timeout(monkeypatch, timeout_exc) -> None:
    attempts = {"n": 0}

    async def flaky_listen(self):  # noqa: ANN001, ANN202
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise timeout_exc  # first pop: idle queue times out
        yield b"queued-task"  # second pop: a real message arrives

    monkeypatch.setattr(ListQueueBroker, "listen", flaky_listen)
    gen = ResilientListQueueBroker("redis://localhost:6379").listen()
    try:
        assert await gen.__anext__() == b"queued-task"  # survived the timeout, delivered the task
        assert attempts["n"] == 2  # it retried rather than dying on the first timeout
    finally:
        await gen.aclose()


async def test_listen_does_not_swallow_unexpected_errors(monkeypatch) -> None:
    async def boom(self):  # noqa: ANN001, ANN202
        raise ValueError("not a timeout")
        yield b""  # pragma: no cover — generator marker

    monkeypatch.setattr(ListQueueBroker, "listen", boom)
    gen = ResilientListQueueBroker("redis://localhost:6379").listen()
    with pytest.raises(ValueError):
        await gen.__anext__()  # genuine errors still surface, not retried forever
