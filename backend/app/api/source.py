"""Source API: serve a file's content for the workspace code panel + hover popover.

Content is stored in Postgres at ingest time, so this is a simple lookup. Returns the full
file as numbered lines plus the highlight range; the client does syntax highlighting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FileNotIndexed, RepoNotFound
from app.db.repositories.files import FileRepository
from app.db.repositories.repos import RepoRepository
from app.db.session import get_session

router = APIRouter(prefix="/repos", tags=["source"])


class Line(BaseModel):
    n: int
    text: str


class SourceOut(BaseModel):
    path: str
    lang: str
    total_lines: int
    highlight_start: int | None
    highlight_end: int | None
    lines: list[Line]


@router.get("/{repo_id}/source", response_model=SourceOut)
async def get_source(
    repo_id: str,
    path: str = Query(...),
    start: int | None = Query(None),
    end: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> SourceOut:
    if not await RepoRepository(session).get(repo_id):
        raise RepoNotFound(f"repo {repo_id} not found")
    file = await FileRepository(session).get_by_path(repo_id, path)
    if not file:
        raise FileNotIndexed(f"{path} is not indexed in this repo")

    raw_lines = file.content.split("\n")
    return SourceOut(
        path=file.path,
        lang=file.lang,
        total_lines=len(raw_lines),
        highlight_start=start,
        highlight_end=end,
        lines=[Line(n=i + 1, text=t) for i, t in enumerate(raw_lines)],
    )
