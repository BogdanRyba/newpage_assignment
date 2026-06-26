"""Dispose the global async engine after each integration test.

pytest-asyncio runs each test in its own event loop; the module-global SQLAlchemy engine
caches asyncpg connections bound to a loop. Disposing within the test's loop closes them
cleanly and avoids 'Event loop is closed' on teardown.
"""

from __future__ import annotations

import pytest

from app.db.session import engine


@pytest.fixture(autouse=True)
async def _dispose_engine():
    yield
    await engine.dispose()
