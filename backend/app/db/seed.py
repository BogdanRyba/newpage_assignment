"""Seeder entrypoint.

Phase 1 fills this in: idempotently ingest the bundled sample repo so the demo
works immediately after `docker compose up`. For now it is a safe no-op so the
`seed` compose service exits cleanly.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger

log = get_logger("seed")


async def main() -> None:
    log.info("seed_skipped", reason="sample ingest wired in Phase 1")


if __name__ == "__main__":
    asyncio.run(main())
