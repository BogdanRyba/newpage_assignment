"""Integration: VersioningService decision tree + compare against real Postgres.

plan_ingest must classify NEW (unknown repo) / NO_OP (commit already ready) / INCREMENTAL
(new commit on a known repo, with the nearest indexed parent). compare must diff two
indexed versions from their manifests with no git and no LLM.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models import File
from app.db.repositories.repos import RepoRepository
from app.db.repositories.versions import RepoVersionRepository, VersionFileRepository
from app.db.session import SessionLocal
from app.services.versioning_service import VersioningService

pytestmark = pytest.mark.integration


async def _blob(s, repo_id: str, path: str, blob_sha: str) -> str:
    f = File(
        repo_id=repo_id, path=path, blob_sha=blob_sha, lang="python", size=1, sha256=blob_sha,
        content="x",
    )
    s.add(f)
    await s.commit()
    await s.refresh(f)
    return f.id


async def test_plan_ingest_new_noop_incremental() -> None:
    async with SessionLocal() as s:
        # Unique per run: integration DB persists rows across runs, and the NEW case
        # asserts the repo is unknown — a fixed URL would be "known" on the second run.
        url = f"https://example.com/acme/widget-{uuid4().hex}"
        repos = RepoRepository(s)

        # NEW: unknown repo (resolve_remote never consulted).
        svc_new = VersioningService(s, resolve_remote=lambda _u, _r: "deadbeef")
        plan = await svc_new.plan_ingest(url)
        assert plan.action == "new"
        assert plan.repo_id is None

        # Seed a known repo with one ready version at commit "c1".
        repo = await repos.create(name="widget", source_url=url)
        versions = RepoVersionRepository(s)
        v1 = await versions.create(
            repo_id=repo.id, ref_name="main", ref_type="branch",
            commit_sha="c1" * 20, parent_version_id=None,
        )
        await versions.finalize(v1.id, file_count=1, chunk_count=1)

        # NO_OP: remote HEAD resolves to the already-ready commit.
        svc_noop = VersioningService(s, resolve_remote=lambda _u, _r: "c1" * 20)
        plan = await svc_noop.plan_ingest(url)
        assert plan.action == "noop"
        assert plan.repo_id == repo.id

        # INCREMENTAL: remote HEAD is a new commit → parent is the nearest ready version.
        svc_inc = VersioningService(s, resolve_remote=lambda _u, _r: "c2" * 20)
        plan = await svc_inc.plan_ingest(url)
        assert plan.action == "incremental"
        assert plan.repo_id == repo.id
        assert plan.parent_version_id == v1.id


async def test_compare_two_versions_from_manifests() -> None:
    async with SessionLocal() as s:
        repo = await RepoRepository(s).create(name="cmp", source_url="https://x/cmp")
        versions = RepoVersionRepository(s)
        vfiles = VersionFileRepository(s)

        # Distinct file rows per blob (content-addressed).
        a1 = await _blob(s, repo.id, "a.py", "blobA1")
        a2 = await _blob(s, repo.id, "a.py", "blobA2")  # a.py changed
        b = await _blob(s, repo.id, "b.py", "blobB")    # removed in head
        c = await _blob(s, repo.id, "c.py", "blobC")    # added in head

        base = await versions.create(
            repo_id=repo.id, ref_name="main", ref_type="branch",
            commit_sha="b" * 40, parent_version_id=None,
        )
        head = await versions.create(
            repo_id=repo.id, ref_name="dev", ref_type="branch",
            commit_sha="h" * 40, parent_version_id=None,
        )
        await vfiles.add_many(base.id, [("a.py", a1), ("b.py", b)])
        await vfiles.add_many(head.id, [("a.py", a2), ("c.py", c)])

        diff = await VersioningService(s).compare(repo.id, "main", "dev")
        assert [c.path for c in diff.added] == ["c.py"]
        assert [c.path for c in diff.removed] == ["b.py"]
        assert [c.path for c in diff.modified] == ["a.py"]
        assert diff.modified[0].old_blob_sha == "blobA1"
        assert diff.modified[0].new_blob_sha == "blobA2"
