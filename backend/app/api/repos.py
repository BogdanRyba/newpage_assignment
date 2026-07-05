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
from app.db.models import IngestJob, Repo, RepoVersion
from app.db.repositories.files import FileRepository
from app.db.repositories.ingest_jobs import IngestJobRepository
from app.db.repositories.repos import RepoRepository
from app.db.repositories.versions import RepoVersionRepository
from app.db.session import get_session
from app.ingestion.clone import repo_name_from_url
from app.ingestion.tasks import ingest_repo
from app.services.suggestions import generate_suggestions
from app.services.versioning_service import VersioningService

router = APIRouter(prefix="/repos", tags=["repos"])


class CreateRepoRequest(BaseModel):
    source_url: str
    ref: str | None = None  # branch/tag/commit; default branch when omitted


class UpdateRepoRequest(BaseModel):
    ref: str | None = None  # which ref's latest tip to pull; default branch when omitted


class RepoOut(BaseModel):
    id: str
    name: str
    source_url: str | None
    status: str
    commit_sha: str | None
    file_count: int
    chunk_count: int
    needs_reingest: bool = False


class VersionOut(BaseModel):
    id: str
    ref_name: str
    ref_type: str
    commit_sha: str
    status: str
    file_count: int
    chunk_count: int


class FileChangeOut(BaseModel):
    path: str
    status: str


class CompareOut(BaseModel):
    added: list[FileChangeOut]
    removed: list[FileChangeOut]
    modified: list[FileChangeOut]


class AuthoredFileOut(BaseModel):
    path: str
    last_author: str | None
    last_commit_sha: str | None
    last_commit_at: str | None


class ProposeRequest(BaseModel):
    question: str


class ResumeRequest(BaseModel):
    decision: str  # "approve" | "reject"


class ProposeOut(BaseModel):
    thread_id: str
    status: str  # "pending_approval" | "done"
    proposal: str | None = None
    answer: str | None = None
    refused: bool = False


class FindingOut(BaseModel):
    dimension: str
    severity: str
    title: str
    path: str
    detail: str


class ReviewOut(BaseModel):
    base_ref: str
    head_ref: str
    files_reviewed: int
    findings: list[FindingOut]
    summary: dict[str, int]


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
        needs_reingest=r.needs_reingest,
    )


def _version_out(v: RepoVersion) -> VersionOut:
    return VersionOut(
        id=v.id,
        ref_name=v.ref_name,
        ref_type=v.ref_type,
        commit_sha=v.commit_sha,
        status=v.status,
        file_count=v.file_count,
        chunk_count=v.chunk_count,
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
    plan = await VersioningService(session).plan_ingest(body.source_url, body.ref)

    # Already indexed at this exact commit (or mid-flight): no new work, just point at it.
    if plan.action in ("noop", "in_progress") and plan.repo_id:
        repo = await repos.get(plan.repo_id)
        job = await jobs.latest_for_repo(plan.repo_id)
        assert repo is not None  # repo_id came from the plan
        return IngestStarted(
            repo_id=repo.id,
            job_id=job.id if job else "",
            name=repo.name,
            status="ready" if plan.action == "noop" else "queued",
        )

    if plan.action == "new" or plan.repo_id is None:
        repo = await repos.create(
            name=repo_name_from_url(body.source_url), source_url=body.source_url
        )
    else:  # incremental on a known repo
        repo = await repos.get(plan.repo_id)
        assert repo is not None
    job = await jobs.create(repo.id)
    await ingest_repo.kiq(
        repo_id=repo.id,
        job_id=job.id,
        source_url=body.source_url,
        ref=body.ref,
        parent_version_id=plan.parent_version_id,
    )
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


@router.get("/{repo_id}/versions", response_model=list[VersionOut])
async def list_versions(
    repo_id: str, session: AsyncSession = Depends(get_session)
) -> list[VersionOut]:
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    versions = await RepoVersionRepository(session).list_for_repo(repo_id)
    return [_version_out(v) for v in versions]


@router.post("/{repo_id}/update", response_model=IngestStarted)
async def update_repo(
    repo_id: str, body: UpdateRepoRequest, session: AsyncSession = Depends(get_session)
) -> IngestStarted:
    """Pull a ref's latest tip and incrementally re-index only what changed since the
    nearest indexed version."""
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    if not repo.source_url:
        raise IngestError("repo has no source_url to update from (uploaded archive)")
    versions = RepoVersionRepository(session)
    parent = None
    if body.ref:
        parent = await versions.latest_for_ref(repo_id, body.ref)
    if parent is None:
        ready = await versions.list_ready(repo_id)
        parent = ready[0] if ready else None
    job = await IngestJobRepository(session).create(repo_id)
    await ingest_repo.kiq(
        repo_id=repo_id,
        job_id=job.id,
        source_url=repo.source_url,
        ref=body.ref,
        parent_version_id=parent.id if parent else None,
    )
    return IngestStarted(repo_id=repo_id, job_id=job.id, name=repo.name, status="queued")


@router.get("/{repo_id}/compare", response_model=CompareOut)
async def compare_versions(
    repo_id: str,
    base: str,
    head: str,
    session: AsyncSession = Depends(get_session),
) -> CompareOut:
    """Diff two indexed versions (by commit sha or ref name) — manifest set-algebra, no LLM."""
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    diff = await VersioningService(session).compare(repo_id, base, head)
    return CompareOut(
        added=[FileChangeOut(path=c.path, status=c.status) for c in diff.added],
        removed=[FileChangeOut(path=c.path, status=c.status) for c in diff.removed],
        modified=[FileChangeOut(path=c.path, status=c.status) for c in diff.modified],
    )


@router.post("/{repo_id}/propose", response_model=ProposeOut)
async def propose_change(
    repo_id: str, body: ProposeRequest, session: AsyncSession = Depends(get_session)
) -> ProposeOut:
    """Draft a high-stakes change and PAUSE for human approval (HITL). Resume via /resume."""
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    from uuid import uuid4

    from app.services.agent_runner import default_deps
    from app.services.agents.hitl import HitlRunner, open_checkpointer

    thread_id = uuid4().hex
    async with open_checkpointer() as cp:
        out = await HitlRunner(default_deps(), cp).start(thread_id, repo_id, body.question)
    if "interrupt" in out:
        return ProposeOut(
            thread_id=thread_id, status="pending_approval", proposal=out["interrupt"]["proposal"]
        )
    ans = out["answer"]
    return ProposeOut(
        thread_id=thread_id, status="done", answer=ans.text, refused=ans.refused
    )


@router.post("/{repo_id}/propose/{thread_id}/resume", response_model=ProposeOut)
async def resume_proposal(
    repo_id: str, thread_id: str, body: ResumeRequest, session: AsyncSession = Depends(get_session)
) -> ProposeOut:
    """Approve or reject a paused proposal; resumes the durable run to completion."""
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    from app.services.agent_runner import default_deps
    from app.services.agents.hitl import HitlRunner, open_checkpointer

    async with open_checkpointer() as cp:
        out = await HitlRunner(default_deps(), cp).resume(thread_id, body.decision)
    ans = out["answer"]
    return ProposeOut(thread_id=thread_id, status="done", answer=ans.text, refused=ans.refused)


@router.get("/{repo_id}/authored", response_model=list[AuthoredFileOut])
async def authored_files(
    repo_id: str, author: str, session: AsyncSession = Depends(get_session)
) -> list[AuthoredFileOut]:
    """Files a developer (case-insensitive substring) last changed — the developer view."""
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    files = await FileRepository(session).files_by_author(repo_id, author)
    return [
        AuthoredFileOut(
            path=f.path,
            last_author=f.last_author,
            last_commit_sha=f.last_commit_sha,
            last_commit_at=f.last_commit_at,
        )
        for f in files
    ]


@router.get("/{repo_id}/review", response_model=ReviewOut)
async def review_versions(
    repo_id: str,
    base: str,
    head: str,
    session: AsyncSession = Depends(get_session),
) -> ReviewOut:
    """Code-review the diff between two indexed versions (parallel security/style/perf)."""
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    from app.core.factory import make_generator
    from app.services.agents.code_review import CodeReviewService

    result = await CodeReviewService(session, make_generator()).review(repo_id, base, head)
    return ReviewOut(
        base_ref=result.base_ref,
        head_ref=result.head_ref,
        files_reviewed=result.files_reviewed,
        findings=[
            FindingOut(
                dimension=f.dimension, severity=f.severity, title=f.title,
                path=f.path, detail=f.detail,
            )
            for f in result.findings
        ],
        summary=result.summary,
    )


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
