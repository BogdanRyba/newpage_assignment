"""Instrumentation decorator (the Decorator pattern, harness component 2).

Wraps a graph node / adapter call with a structured log line (and, in Phase 4, an OTel
span) — latency, node name, errors — without polluting the node body. Agent logs are tagged
`[daedalus]`. Keeps cross-cutting concerns out of the business logic.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.logging import daedalus_logger

T = TypeVar("T")


def instrument(name: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            log = daedalus_logger()
            start = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                log.error("node_error", node=name, error=str(exc))
                raise
            log.info("node", node=name, ms=round((time.perf_counter() - start) * 1000, 1))
            return result

        return wrapper

    return decorator
