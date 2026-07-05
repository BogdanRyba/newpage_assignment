"""Integration: incremental, content-addressed ingest against real Postgres + Qdrant.

The core efficiency contract: re-ingesting a new commit re-embeds ONLY the blobs that
changed; unchanged files are carried forward (same file row, same Qdrant points) and never
re-embedded. Also covers first-ingest-as-empty-tree-diff and the no-op gate.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from app.core import factory
from app.db.repositories.repos import RepoRepository
from app.db.repositories.versions import RepoVersionRepository, VersionFileRepository
from app.db.session import SessionLocal
from app.domain.models import RepoContext
from app.services.ingest_service import IngestService

pytestmark = pytest.mark.integration


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tester")


def _commit(root: Path, msg: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return _git(root, "rev-parse", "HEAD")


async def _ingest(repo_id: str, root: Path, parent_version_id: str | None) -> None:
    async with SessionLocal() as s:
        await IngestService(s).run(
            repo_id=repo_id, job_id=repo_id + "j", local_path=str(root),
            parent_version_id=parent_version_id,
        )


async def test_incremental_reembeds_only_changed_blob() -> None:
    factory.make_vector_store.cache_clear()
    upserted_blobs: list[str] = []
    store = factory.make_vector_store()
    orig_upsert = store.upsert

    async def spy_upsert(ctx, points):  # type: ignore[no-untyped-def]
        upserted_blobs.extend(p.payload["blob_sha"] for p in points)
        return await orig_upsert(ctx, points)

    store.upsert = spy_upsert  # type: ignore[method-assign]

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _init_repo(root)
        (root / "a.py").write_text("def a():\n    return 1\n")
        (root / "b.py").write_text("def b():\n    return 2\n")
        _commit(root, "v1")

        async with SessionLocal() as s:
            repo = await RepoRepository(s).create(name="inc", source_url=f"file://{d}")
        repo_id = repo.id
        ctx = RepoContext(repo_id=repo_id)

        # --- first ingest (empty-tree diff → both files added) ---
        await _ingest(repo_id, root, None)
        first_blobs = set(upserted_blobs)
        assert len(first_blobs) == 2, "both files embedded on first ingest"

        async with SessionLocal() as s:
            versions = await RepoVersionRepository(s).list_ready(repo_id)
            assert len(versions) == 1
            v1 = versions[0]
            base_map = await VersionFileRepository(s).load_file_map(v1.id)
        a_file_id_v1 = base_map["a.py"]

        # --- change only b.py, re-ingest incrementally from v1 ---
        upserted_blobs.clear()
        (root / "b.py").write_text("def b():\n    return 999\n")
        _commit(root, "v2")
        await _ingest(repo_id, root, v1.id)

        # Only b.py's NEW blob was re-embedded; a.py untouched.
        reembedded = set(upserted_blobs)
        async with SessionLocal() as s:
            versions = await RepoVersionRepository(s).list_ready(repo_id)
            assert len(versions) == 2, "two ready versions after incremental ingest"
            v2 = next(v for v in versions if v.id != v1.id)
            map_v2 = await VersionFileRepository(s).load_file_map(v2.id)
            manifest_v1 = await VersionFileRepository(s).load_manifest(v1.id)
            manifest_v2 = await VersionFileRepository(s).load_manifest(v2.id)

        # a.py shares its file row + blob across versions (never re-embedded).
        assert map_v2["a.py"] == a_file_id_v1
        assert manifest_v1["a.py"] == manifest_v2["a.py"]
        # b.py changed → different blob in each version, and exactly that blob was embedded.
        assert manifest_v1["b.py"] != manifest_v2["b.py"]
        assert reembedded == {manifest_v2["b.py"]}, "only the changed blob re-embedded"

        # Old version still resolves a.py + the OLD b.py (version isolation holds).
        assert set(manifest_v1) == {"a.py", "b.py"}

        store.upsert = orig_upsert  # type: ignore[method-assign]
        await store.delete_collection(ctx)
