"""Integration: the versioning repositories against real Postgres.

Asserts the manifest round-trips (load_manifest reconstructs path→blob), the no-op
gate (get_by_commit), canonical-path lookup (paths_for, the shared-blob citation fix),
and the set-membership refcount (FK RESTRICT blocks deleting a referenced blob).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import File
from app.db.repositories.repos import RepoRepository
from app.db.repositories.versions import RepoVersionRepository, VersionFileRepository
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


async def _make_file(session, repo_id: str, path: str, blob_sha: str) -> File:
    f = File(
        repo_id=repo_id, path=path, blob_sha=blob_sha, lang="python", size=1, sha256=blob_sha,
        content="x",
    )
    session.add(f)
    await session.commit()
    await session.refresh(f)
    return f


async def test_manifest_roundtrip_and_no_op_gate_and_refcount() -> None:
    async with SessionLocal() as s:
        repo = await RepoRepository(s).create(name="vtest", source_url="https://x/vtest")
        versions = RepoVersionRepository(s)
        manifest_repo = VersionFileRepository(s)

        f_a = await _make_file(s, repo.id, "a.py", "blobA")
        f_shared = await _make_file(s, repo.id, "shared.py", "blobS")

        v1 = await versions.create(
            repo_id=repo.id, ref_name="main", ref_type="branch",
            commit_sha="c" * 40, parent_version_id=None,
        )
        await manifest_repo.add_many(v1.id, [("a.py", f_a.id), ("shared.py", f_shared.id)])

        # Manifest round-trips to path→blob.
        assert await manifest_repo.load_manifest(v1.id) == {"a.py": "blobA", "shared.py": "blobS"}

        # No-op gate: the same commit resolves to the same version row.
        assert (await versions.get_by_commit(repo.id, "c" * 40)).id == v1.id
        assert await versions.get_by_commit(repo.id, "d" * 40) is None

        # Canonical-path lookup (shared-blob citation fix): file_id → its path in v1.
        assert await manifest_repo.paths_for(v1.id, [f_a.id]) == {f_a.id: "a.py"}

        # Refcount: a blob referenced by a version cannot be deleted (FK RESTRICT).
        with pytest.raises(IntegrityError):
            await s.execute(text("DELETE FROM files WHERE id = :i").bindparams(i=f_a.id))
        await s.rollback()
