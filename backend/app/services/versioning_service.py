"""Versioning use-case: decide how to ingest a ref, and compare two indexed versions.

`plan_ingest` is the pre-enqueue decision tree (NEW / NO_OP / IN_PROGRESS / INCREMENTAL)
— it answers "have we seen this repo? this exact commit? which parent to diff from?"
using a cheap `git ls-remote` (no clone). `compare` diffs two indexed versions purely
from their Postgres manifests (no git, no LLM), feeding the future code-review agent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IngestError
from app.db.repositories.repos import RepoRepository
from app.db.repositories.versions import RepoVersionRepository, VersionFileRepository
from app.domain.versioning.diff import VersionDiff, diff_manifests
from app.ingestion.clone import resolve_ref_remote

Action = Literal["new", "noop", "in_progress", "incremental"]


class IngestPlan(BaseModel):
    """The decision for one ingest request. The API acts on it (create/enqueue/skip)."""

    action: Action
    repo_id: str | None = None
    parent_version_id: str | None = None
    commit_sha: str | None = None
    ref: str | None = None


class VersioningService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        resolve_remote: Callable[[str, str], str | None] = resolve_ref_remote,
    ) -> None:
        self.repos = RepoRepository(session)
        self.versions = RepoVersionRepository(session)
        self.vfiles = VersionFileRepository(session)
        self._resolve_remote = resolve_remote  # injectable for deterministic tests

    async def plan_ingest(self, source_url: str, ref: str | None = None) -> IngestPlan:
        repo = await self.repos.get_by_source_url(source_url)
        if repo is None:
            return IngestPlan(action="new", ref=ref)

        head = self._resolve_remote(source_url, ref or "HEAD")
        if head is not None:
            existing = await self.versions.get_by_commit(repo.id, head)
            if existing is not None and existing.status == "ready":
                return IngestPlan(action="noop", repo_id=repo.id, commit_sha=head, ref=ref)
            if existing is not None and existing.status in ("indexing", "pending"):
                return IngestPlan(
                    action="in_progress", repo_id=repo.id, commit_sha=head, ref=ref
                )

        # A new commit on a known repo → incremental from the nearest indexed tip.
        parent = None
        if ref:
            parent = await self.versions.latest_for_ref(repo.id, ref)
        if parent is None:
            ready = await self.versions.list_ready(repo.id)
            parent = ready[0] if ready else None
        return IngestPlan(
            action="incremental",
            repo_id=repo.id,
            parent_version_id=parent.id if parent else None,
            commit_sha=head,
            ref=ref,
        )

    async def compare(self, repo_id: str, base_ref: str, head_ref: str) -> VersionDiff:
        base = await self._resolve_version(repo_id, base_ref)
        head = await self._resolve_version(repo_id, head_ref)
        base_manifest = await self.vfiles.load_manifest(base.id)
        head_manifest = await self.vfiles.load_manifest(head.id)
        return diff_manifests(base_manifest, head_manifest)

    async def _resolve_version(self, repo_id: str, ref: str):  # noqa: ANN202 - RepoVersion
        """Resolve a ref to an indexed version: by commit sha, then by ref name (latest)."""
        by_commit = await self.versions.get_by_commit(repo_id, ref)
        if by_commit is not None:
            return by_commit
        by_ref = await self.versions.latest_for_ref(repo_id, ref)
        if by_ref is not None:
            return by_ref
        raise IngestError(f"no indexed version for ref '{ref}' in repo {repo_id}")
