"""RAG integration: ingest the sample repo, then prove retrieval finds the right code.

Uses real Postgres + Qdrant; embeddings are the deterministic local provider (offline).
Per the testing standard, this asserts the retrieved chunk actually contains the expected
symbol — not merely that "something came back". Run with:

    docker compose run --rm -e EMBEDDING_PROVIDER=local api \
        sh -c "alembic upgrade head && pytest -m integration -q"
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.factory import make_embedder, make_vector_store
from app.db.repositories.ingest_jobs import IngestJobRepository
from app.db.repositories.repos import RepoRepository
from app.db.session import SessionLocal
from app.domain.models import RepoContext

pytestmark = pytest.mark.integration

SAMPLE = Path(__file__).resolve().parents[2] / "sample_repo"


async def test_ingest_then_retrieve_finds_expected_symbol() -> None:
    assert get_settings().embedding_provider == "local", "run with EMBEDDING_PROVIDER=local"
    from app.services.ingest_service import IngestService

    async with SessionLocal() as session:
        repos, jobs = RepoRepository(session), IngestJobRepository(session)
        repo = await repos.create(name="itest", source_url=None)
        job = await jobs.create(repo.id)
        await IngestService(session).run(repo_id=repo.id, job_id=job.id, local_path=str(SAMPLE))

        fresh = await repos.get(repo.id)
        assert fresh is not None
        assert fresh.status == "ready"
        assert fresh.file_count >= 2  # calculator.py + tokens.ts (+ README)
        assert fresh.chunk_count >= 3

    ctx = RepoContext(repo_id=repo.id)
    vectors = make_vector_store()
    try:
        assert await vectors.count(ctx) == fresh.chunk_count  # Qdrant ↔ Postgres agree

        embedder = make_embedder()
        qv = await embedder.embed_query("Calculator add to the running total")
        hits = await vectors.search_dense(ctx, qv, limit=5)
        assert hits, "retrieval returned nothing"

        # The expected code must actually be among the retrieved chunks.
        blob = " ".join(
            (h.payload.get("text") or "") + " " + (h.payload.get("symbol") or "") for h in hits
        )
        assert "Calculator" in blob or "add" in blob
        assert any("calculator.py" in (h.payload.get("path") or "") for h in hits)

        # Idempotency: a second ingest must not duplicate points.
        async with SessionLocal() as session:
            jobs2 = IngestJobRepository(session)
            job2 = await jobs2.create(repo.id)
            await IngestService(session).run(
                repo_id=repo.id, job_id=job2.id, local_path=str(SAMPLE)
            )
        assert await vectors.count(ctx) == fresh.chunk_count
    finally:
        await vectors.delete_collection(ctx)
