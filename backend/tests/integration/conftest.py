"""Per-test cleanup for integration tests.

pytest-asyncio runs each test in its own event loop; our module-global SQLAlchemy engine
and the lru_cached Qdrant client cache connections bound to a loop. We close them and clear
the DI caches after each test so the next test rebuilds fresh clients in its own loop —
otherwise asyncpg/qdrant raise 'Event loop is closed' on reuse.
"""

from __future__ import annotations

import pytest

from app.core import factory
from app.db.session import engine


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    try:
        await factory.make_vector_store().aclose()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    for fn in (
        factory.make_vector_store,
        factory.make_embedder,
        factory.make_sparse_embedder,
        factory.make_generator,
        factory.make_graph_store,
        factory.make_parser,
    ):
        fn.cache_clear()
    await engine.dispose()
