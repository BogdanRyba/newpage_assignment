"""Source API: serve a file's content for the workspace code panel + hover popover.

Content is stored in Postgres at ingest time, so this is a simple lookup. Returns the full
file as numbered lines plus the highlight range; the client does syntax highlighting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
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
    # True when the original bytes are available to render visually (PDFs). The UI uses
    # this to offer a "Document" view served by GET /{repo_id}/source/raw.
    has_raw: bool = False


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
        has_raw=file.raw is not None,
    )


@router.get("/{repo_id}/source/raw")
async def get_source_raw(
    repo_id: str,
    path: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Serve the original document bytes (PDF) for the visual viewer. Rendered inline by the
    browser in an iframe; the extracted text is still served by /source for chunking/citation."""
    if not await RepoRepository(session).get(repo_id):
        raise RepoNotFound(f"repo {repo_id} not found")
    file = await FileRepository(session).get_by_path(repo_id, path)
    if not file:
        raise FileNotIndexed(f"{path} is not indexed in this repo")
    if file.raw is None:
        raise FileNotIndexed(f"{path} has no stored document bytes to render")

    filename = file.path.split("/")[-1]
    return Response(
        content=file.raw,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
