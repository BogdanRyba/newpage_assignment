"""Repositories for `repo_versions` and `version_files` (the path→blob manifest).

DB access lives here, never in endpoints. A version row is one indexed snapshot of a
repo at a commit; the manifest binds each repo-relative path to the blob (file row)
present at that path in that version. Unchanged blobs are shared across versions, so
the manifest — not Qdrant — is the source of truth for "which version has which file".
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import File, RepoVersion, VersionFile


class RepoVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        repo_id: str,
        ref_name: str,
        ref_type: str,
        commit_sha: str,
        parent_version_id: str | None,
    ) -> RepoVersion:
        version = RepoVersion(
            repo_id=repo_id,
            ref_name=ref_name,
            ref_type=ref_type,
            commit_sha=commit_sha,
            parent_version_id=parent_version_id,
            status="indexing",
        )
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def get(self, version_id: str) -> RepoVersion | None:
        return await self.session.get(RepoVersion, version_id)

    async def get_by_commit(self, repo_id: str, commit_sha: str) -> RepoVersion | None:
        """The no-op gate: a commit is indexed at most once per repo."""
        return await self.session.scalar(
            select(RepoVersion).where(
                RepoVersion.repo_id == repo_id, RepoVersion.commit_sha == commit_sha
            )
        )

    async def latest_for_ref(self, repo_id: str, ref_name: str) -> RepoVersion | None:
        """Most recent version for a moving ref (e.g. the current tip of `main`)."""
        return await self.session.scalar(
            select(RepoVersion)
            .where(RepoVersion.repo_id == repo_id, RepoVersion.ref_name == ref_name)
            .order_by(RepoVersion.created_at.desc())
        )

    async def list_ready(self, repo_id: str) -> list[RepoVersion]:
        result = await self.session.execute(
            select(RepoVersion)
            .where(RepoVersion.repo_id == repo_id, RepoVersion.status == "ready")
            .order_by(RepoVersion.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_repo(self, repo_id: str) -> list[RepoVersion]:
        result = await self.session.execute(
            select(RepoVersion)
            .where(RepoVersion.repo_id == repo_id)
            .order_by(RepoVersion.created_at.desc())
        )
        return list(result.scalars().all())

    async def set_status(self, version_id: str, status: str) -> None:
        version = await self.session.get(RepoVersion, version_id)
        if version:
            version.status = status
            await self.session.commit()

    async def finalize(self, version_id: str, *, file_count: int, chunk_count: int) -> None:
        version = await self.session.get(RepoVersion, version_id)
        if version:
            version.status = "ready"
            version.file_count = file_count
            version.chunk_count = chunk_count
            version.ingested_at = datetime.now(UTC)
            await self.session.commit()


class VersionFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_many(self, version_id: str, entries: list[tuple[str, str]]) -> None:
        """Insert manifest rows. ``entries`` is a list of (path, file_id)."""
        for path, file_id in entries:
            self.session.add(VersionFile(version_id=version_id, path=path, file_id=file_id))
        await self.session.commit()

    async def load_manifest(self, version_id: str) -> dict[str, str]:
        """path → blob_sha for a version (joined through files). The comparison input."""
        result = await self.session.execute(
            select(VersionFile.path, File.blob_sha)
            .join(File, File.id == VersionFile.file_id)
            .where(VersionFile.version_id == version_id)
        )
        return {path: blob for path, blob in result.all() if blob is not None}

    async def load_file_map(self, version_id: str) -> dict[str, str]:
        """path → file_id for a version. Unchanged paths in an incremental ingest carry
        their parent file_id forward through this map (so they are never re-embedded)."""
        result = await self.session.execute(
            select(VersionFile.path, VersionFile.file_id).where(
                VersionFile.version_id == version_id
            )
        )
        return {path: file_id for path, file_id in result.all()}

    async def paths_for(self, version_id: str, file_ids: list[str]) -> dict[str, str]:
        """file_id → canonical path for this version. Used to fix citation paths when a
        blob is shared across multiple paths (payload path is only a display fallback)."""
        if not file_ids:
            return {}
        result = await self.session.execute(
            select(VersionFile.file_id, VersionFile.path).where(
                VersionFile.version_id == version_id, VersionFile.file_id.in_(file_ids)
            )
        )
        return {file_id: path for file_id, path in result.all()}

    async def file_ids_in(self, version_id: str) -> list[str]:
        result = await self.session.execute(
            select(VersionFile.file_id).where(VersionFile.version_id == version_id)
        )
        return list(result.scalars().all())

    async def contents_for(self, version_id: str, paths: list[str]) -> dict[str, str]:
        """path → file content for the given paths in a version (for code review)."""
        if not paths:
            return {}
        result = await self.session.execute(
            select(VersionFile.path, File.content)
            .join(File, File.id == VersionFile.file_id)
            .where(VersionFile.version_id == version_id, VersionFile.path.in_(paths))
        )
        return {path: content for path, content in result.all()}
