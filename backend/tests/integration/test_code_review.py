"""Integration: code-review agent over two indexed versions (real Postgres).

Builds a base + head version with changed file content, runs the parallel reviewers with a
scripted generator, and asserts the merged findings reference the changed files. Also covers
the no-change case (nothing to review).
"""

from __future__ import annotations

import pytest

from app.db.models import File
from app.db.repositories.repos import RepoRepository
from app.db.repositories.versions import RepoVersionRepository, VersionFileRepository
from app.db.session import SessionLocal
from app.services.agents.code_review import CodeReviewService
from tests.fakes import FakeGenerator

pytestmark = pytest.mark.integration


async def _blob(s, repo_id, path, blob_sha, content):  # noqa: ANN001, ANN202
    f = File(
        repo_id=repo_id, path=path, blob_sha=blob_sha, lang="python", size=len(content),
        sha256=blob_sha, content=content,
    )
    s.add(f)
    await s.commit()
    await s.refresh(f)
    return f.id


async def test_review_reports_findings_on_changed_files() -> None:
    async with SessionLocal() as s:
        repo = await RepoRepository(s).create(name="rev", source_url="https://x/rev")
        versions = RepoVersionRepository(s)
        vfiles = VersionFileRepository(s)
        a1 = await _blob(s, repo.id, "auth.py", "b1", "def login(): pass")
        a2 = await _blob(s, repo.id, "auth.py", "b2", "def login(pw): exec(pw)")  # changed
        base = await versions.create(
            repo_id=repo.id, ref_name="main", ref_type="branch", commit_sha="m" * 40,
            parent_version_id=None,
        )
        head = await versions.create(
            repo_id=repo.id, ref_name="dev", ref_type="branch", commit_sha="d" * 40,
            parent_version_id=None,
        )
        await vfiles.add_many(base.id, [("auth.py", a1)])
        await vfiles.add_many(head.id, [("auth.py", a2)])

        # One findings JSON per reviewer dimension (order-independent: merged is the union).
        gen = FakeGenerator(
            [
                '{"findings":[{"severity":"high","title":"exec on user input","path":"auth.py"}]}',
                '{"findings":[{"severity":"low","title":"missing type hints","path":"auth.py"}]}',
                '{"findings":[]}',
            ]
        )
        result = await CodeReviewService(s, gen).review(repo.id, "main", "dev")

    assert result.files_reviewed == 1
    titles = {f.title for f in result.findings}
    assert "exec on user input" in titles
    # High severity sorts before low.
    assert result.findings[0].severity == "high"


async def test_review_with_no_changes_returns_empty() -> None:
    async with SessionLocal() as s:
        repo = await RepoRepository(s).create(name="rev2", source_url="https://x/rev2")
        versions = RepoVersionRepository(s)
        vfiles = VersionFileRepository(s)
        a1 = await _blob(s, repo.id, "x.py", "bx", "x = 1")
        base = await versions.create(
            repo_id=repo.id, ref_name="main", ref_type="branch", commit_sha="m" * 40,
            parent_version_id=None,
        )
        head = await versions.create(
            repo_id=repo.id, ref_name="dev", ref_type="branch", commit_sha="d" * 40,
            parent_version_id=None,
        )
        await vfiles.add_many(base.id, [("x.py", a1)])
        await vfiles.add_many(head.id, [("x.py", a1)])  # identical → no change

        gen = FakeGenerator(["should-not-be-called"])
        result = await CodeReviewService(s, gen).review(repo.id, "main", "dev")

    assert result.files_reviewed == 0
    assert result.findings == []
