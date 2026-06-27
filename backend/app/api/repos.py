"""Repos API: create/ingest, list, detail, and SSE ingest progress.

Thin handlers: validate, call the repo layer + enqueue the Taskiq job, shape the response.
The actual pipeline runs in the worker; progress streams back over Redis → SSE.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import redis.asyncio as redis
from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_settings
from app.core.errors import IngestError, RepoNotFound
from app.core.progress import channel
from app.core.uploads import store_upload
from app.db.models import IngestJob, Repo
from app.db.repositories.files import FileRepository
from app.db.repositories.ingest_jobs import IngestJobRepository
from app.db.repositories.repos import RepoRepository
from app.db.session import get_session
from app.ingestion.clone import repo_name_from_url
from app.ingestion.tasks import ingest_repo
from app.services.suggestions import generate_suggestions

router = APIRouter(prefix="/repos", tags=["repos"])


class CreateRepoRequest(BaseModel):
    source_url: str


class RepoOut(BaseModel):
    id: str
    name: str
    source_url: str | None
    status: str
    commit_sha: str | None
    file_count: int
    chunk_count: int


class JobOut(BaseModel):
    id: str
    status: str
    phase: str
    files_done: int
    chunks_done: int
    pct: int
    error: str | None


class IngestStarted(BaseModel):
    repo_id: str
    job_id: str
    name: str
    status: str


class RepoDetail(BaseModel):
    repo: RepoOut
    job: JobOut | None


class SuggestionsOut(BaseModel):
    suggestions: list[str]


def _repo_out(r: Repo) -> RepoOut:
    return RepoOut(
        id=r.id,
        name=r.name,
        source_url=r.source_url,
        status=r.status,
        commit_sha=r.commit_sha,
        file_count=r.file_count,
        chunk_count=r.chunk_count,
    )


def _job_out(j: IngestJob) -> JobOut:
    return JobOut(
        id=j.id,
        status=j.status,
        phase=j.phase,
        files_done=j.files_done,
        chunks_done=j.chunks_done,
        pct=j.pct,
        error=j.error,
    )


@router.post("", response_model=IngestStarted)
async def create_repo(
    body: CreateRepoRequest, session: AsyncSession = Depends(get_session)
) -> IngestStarted:
    if not body.source_url.strip():
        raise IngestError("source_url is required")
    repos, jobs = RepoRepository(session), IngestJobRepository(session)
    repo = await repos.create(name=repo_name_from_url(body.source_url), source_url=body.source_url)
    job = await jobs.create(repo.id)
    await ingest_repo.kiq(repo_id=repo.id, job_id=job.id, source_url=body.source_url)
    return IngestStarted(repo_id=repo.id, job_id=job.id, name=repo.name, status="queued")


@router.post("/upload", response_model=IngestStarted)
async def upload_repo(
    file: UploadFile, session: AsyncSession = Depends(get_session)
) -> IngestStarted:
    if not (file.filename or "").endswith(".zip"):
        raise IngestError("please upload a .zip archive")
    data = await file.read()
    repos, jobs = RepoRepository(session), IngestJobRepository(session)
    name = (file.filename or "upload.zip").removesuffix(".zip")
    repo = await repos.create(name=name, source_url=None)
    job = await jobs.create(repo.id)
    await store_upload(job.id, data)
    await ingest_repo.kiq(repo_id=repo.id, job_id=job.id, has_upload=True)
    return IngestStarted(repo_id=repo.id, job_id=job.id, name=repo.name, status="queued")


@router.get("", response_model=list[RepoOut])
async def list_repos(session: AsyncSession = Depends(get_session)) -> list[RepoOut]:
    return [_repo_out(r) for r in await RepoRepository(session).list()]


@router.get("/{repo_id}", response_model=RepoDetail)
async def get_repo(repo_id: str, session: AsyncSession = Depends(get_session)) -> RepoDetail:
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    job = await IngestJobRepository(session).latest_for_repo(repo_id)
    return RepoDetail(repo=_repo_out(repo), job=_job_out(job) if job else None)


@router.get("/{repo_id}/suggestions", response_model=SuggestionsOut)
async def repo_suggestions(
    repo_id: str, session: AsyncSession = Depends(get_session)
) -> SuggestionsOut:
    """LLM-generated starter questions grounded in this repo's files/symbols (cached per repo)."""
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    symbol_map = await FileRepository(session).symbol_map(repo_id)
    return SuggestionsOut(suggestions=await generate_suggestions(repo_id, symbol_map))


@router.get("/{repo_id}/ingest/stream")
async def ingest_stream(
    repo_id: str, session: AsyncSession = Depends(get_session)
) -> EventSourceResponse:
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    job = await IngestJobRepository(session).latest_for_repo(repo_id)
    snapshot = _job_out(job).model_dump() if job else {"phase": "queued", "pct": 0}

    async def gen() -> AsyncIterator[dict]:
        # Initial snapshot so a late subscriber still sees current state.
        yield {"event": "progress", "data": json.dumps({"type": "progress", **snapshot})}
        if snapshot.get("status") in {"done", "failed"} or snapshot.get("pct") == 100:
            yield {"event": "done", "data": json.dumps({"type": "done"})}
            return

        client = redis.from_url(get_settings().redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel(repo_id))
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = msg["data"].decode("utf-8")
                yield {"event": "progress", "data": data}
                evt = json.loads(data)
                if evt.get("phase") == "done" or evt.get("type") == "error":
                    yield {"event": "done", "data": json.dumps({"type": "done"})}
                    break
        finally:
            await pubsub.unsubscribe(channel(repo_id))
            await pubsub.aclose()
            await client.aclose()

    return EventSourceResponse(gen())
