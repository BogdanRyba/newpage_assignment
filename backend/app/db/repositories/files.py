"""Repository for `files` (with full content, served to the UI source panel) and `chunks`."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, File, VersionFile


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        repo_id: str,
        path: str,
        lang: str,
        size: int,
        sha256: str,
        content: str,
        raw: bytes | None = None,
        blob_sha: str | None = None,
    ) -> File:
        existing = await self.session.scalar(
            select(File).where(File.repo_id == repo_id, File.path == path)
        )
        if existing:
            existing.lang = lang
            existing.size = size
            existing.sha256 = sha256
            existing.content = content
            existing.raw = raw
            existing.blob_sha = blob_sha if blob_sha is not None else sha256
            file = existing
        else:
            file = File(
                repo_id=repo_id,
                path=path,
                lang=lang,
                size=size,
                sha256=sha256,
                content=content,
                raw=raw,
                blob_sha=blob_sha if blob_sha is not None else sha256,
            )
            self.session.add(file)
        await self.session.commit()
        await self.session.refresh(file)
        return file

    async def get_or_create_blob(
        self,
        *,
        repo_id: str,
        blob_sha: str,
        path: str,
        lang: str,
        size: int,
        sha256: str,
        content: str,
        raw: bytes | None = None,
    ) -> tuple[File, bool]:
        """Content-addressed file creation: one immutable row per (repo, blob).

        Returns (file, created). When the blob already exists (shared across versions or
        paths) the existing row is returned with created=False so the caller can skip
        re-chunking/re-embedding — the heart of "never re-index unchanged content".
        Rows are never mutated: a changed file is a NEW blob → a NEW row, leaving older
        versions pointing at the old blob intact.
        """
        existing = await self.session.scalar(
            select(File).where(File.repo_id == repo_id, File.blob_sha == blob_sha)
        )
        if existing is not None:
            return existing, False
        file = File(
            repo_id=repo_id,
            path=path,
            blob_sha=blob_sha,
            lang=lang,
            size=size,
            sha256=sha256,
            content=content,
            raw=raw,
        )
        self.session.add(file)
        await self.session.commit()
        await self.session.refresh(file)
        return file, True

    async def set_authorship(
        self,
        file_id: str,
        *,
        last_author: str,
        last_author_email: str,
        last_commit_sha: str,
        last_commit_at: str,
        commit_history: list[dict],
    ) -> None:
        """Store git authorship for a file row (called at ingest for git sources)."""
        f = await self.session.get(File, file_id)
        if f is not None:
            f.last_author = last_author
            f.last_author_email = last_author_email
            f.last_commit_sha = last_commit_sha
            f.last_commit_at = last_commit_at
            f.commit_history = commit_history
            await self.session.commit()

    async def get_by_path(self, repo_id: str, path: str) -> File | None:
        # NOTE: under versioning a path can have multiple blobs (rows). This returns one
        # of them (latest by row order); version-scoped source lookup is a later step.
        return await self.session.scalar(
            select(File).where(File.repo_id == repo_id, File.path == path).order_by(File.id.desc())
        )

    async def files_by_author(self, repo_id: str, author: str) -> list[File]:
        """Files this developer last changed (case-insensitive substring) — for dev search.

        Deduped by path (a path can have several blob rows across versions), keeping the most
        recently created row per path.
        """
        rows = await self.session.execute(
            select(File)
            .where(File.repo_id == repo_id, File.last_author.ilike(f"%{author}%"))
            .order_by(File.path, File.id.desc())
        )
        seen: set[str] = set()
        out: list[File] = []
        for f in rows.scalars().all():
            if f.path in seen:
                continue
            seen.add(f.path)
            out.append(f)
        return out

    async def orphan_blobs(self, repo_id: str) -> list[tuple[str, str | None]]:
        """(file_id, blob_sha) for blobs no version references — GC candidates.

        A blob orphans only once every version that contained it is gone (the version_files
        FK RESTRICT enforces this), so this is safe to run after any ingest/version drop.
        """
        rows = await self.session.execute(
            select(File.id, File.blob_sha)
            .outerjoin(VersionFile, VersionFile.file_id == File.id)
            .where(File.repo_id == repo_id, VersionFile.file_id.is_(None))
        )
        return [(fid, blob) for fid, blob in rows.all()]

    async def delete(self, file_id: str) -> None:
        """Delete a file row (its chunks cascade). Caller deletes Qdrant points first."""
        await self.session.execute(delete(File).where(File.id == file_id))
        await self.session.commit()

    async def symbol_map(
        self, repo_id: str, file_cap: int = 40, sym_cap: int = 12
    ) -> list[tuple[str, list[str]]]:
        """A compact map of `path → [symbols]` for the repo — the basis for LLM-generated
        starter questions. Caps keep the prompt small on large repos."""
        rows = await self.session.execute(
            select(File.path, Chunk.symbol)
            .join(Chunk, Chunk.file_id == File.id)
            .where(File.repo_id == repo_id, Chunk.symbol.isnot(None))
            .order_by(File.path)
        )
        grouped: dict[str, list[str]] = {}
        for path, symbol in rows.all():
            syms = grouped.setdefault(path, [])
            if symbol not in syms and len(syms) < sym_cap:
                syms.append(symbol)
        return list(grouped.items())[:file_cap]


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_many(
        self,
        *,
        file_id: str,
        repo_id: str,
        rows: list[dict],
    ) -> None:
        """rows: [{symbol, kind, start_line, end_line, qdrant_point_id}]."""
        for r in rows:
            self.session.add(Chunk(file_id=file_id, repo_id=repo_id, **r))
        await self.session.commit()

    async def delete_for_file(self, file_id: str) -> None:
        await self.session.execute(delete(Chunk).where(Chunk.file_id == file_id))
        await self.session.commit()

    async def count_for_repo(self, repo_id: str) -> int:
        result = await self.session.execute(select(Chunk.id).where(Chunk.repo_id == repo_id))
        return len(result.all())
