"""Integration: ingest captures real git authorship, and the Postgres adapter serves it.

Proves the Phase 1B chain end-to-end against real git + Postgres: a commit by a known author
becomes queryable authorship the dev-search persona grounds its answers on.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from app.adapters.authorship.postgres import PostgresAuthorship
from app.db.repositories.repos import RepoRepository
from app.db.session import SessionLocal
from app.domain.models import RepoContext
from app.services.ingest_service import IngestService

pytestmark = pytest.mark.integration


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


async def test_ingest_captures_authorship_then_postgres_adapter_serves_it() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "ada@example.com")
        _git(root, "config", "user.name", "Ada Lovelace")
        (root / "store.py").write_text("def search():\n    return []\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "add search")

        async with SessionLocal() as s:
            repo = await RepoRepository(s).create(name="auth", source_url=f"file://{d}")
            await IngestService(s).run(
                repo_id=repo.id, job_id=repo.id + "j", local_path=str(root)
            )
        repo_id = repo.id

        fa = await PostgresAuthorship().file_authorship(RepoContext(repo_id=repo_id), "store.py")
        assert fa is not None
        assert fa.last_author == "Ada Lovelace"
        assert fa.last_author_email == "ada@example.com"
        assert fa.last_commit_sha  # a real sha was captured
        assert any(c.author == "Ada Lovelace" for c in fa.recent_commits)

        # Unknown file → no authorship (the dev-search refusal path).
        missing = await PostgresAuthorship().file_authorship(
            RepoContext(repo_id=repo_id), "nope.py"
        )
        assert missing is None

        # Developer view: searching by (partial) author name lists the files they changed.
        from app.db.repositories.files import FileRepository

        async with SessionLocal() as s:
            authored = await FileRepository(s).files_by_author(repo_id, "ada")
            none_for_nobody = await FileRepository(s).files_by_author(repo_id, "nobody")
        assert [f.path for f in authored] == ["store.py"]
        assert none_for_nobody == []
