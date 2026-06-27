"""Repository for `files` (with full content, served to the UI source panel) and `chunks`."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, File


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self, *, repo_id: str, path: str, lang: str, size: int, sha256: str, content: str
    ) -> File:
        existing = await self.session.scalar(
            select(File).where(File.repo_id == repo_id, File.path == path)
        )
        if existing:
            existing.lang, existing.size, existing.sha256, existing.content = (
                lang,
                size,
                sha256,
                content,
            )
            file = existing
        else:
            file = File(
                repo_id=repo_id, path=path, lang=lang, size=size, sha256=sha256, content=content
            )
            self.session.add(file)
        await self.session.commit()
        await self.session.refresh(file)
        return file

    async def get_by_path(self, repo_id: str, path: str) -> File | None:
        return await self.session.scalar(
            select(File).where(File.repo_id == repo_id, File.path == path)
        )

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
