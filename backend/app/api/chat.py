"""Chat API: ask a question, stream the answer + citations over SSE.

Thin handler — it validates the repo, persists the turn, and delegates the actual work to
the AgentRunner (Daedalus). The validated answer is streamed as tokens, then a citations (or
no_sources) event, then done.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.errors import RepoNotFound, RepoNotReady
from app.db.repositories.chat import ChatRepository
from app.db.repositories.repos import RepoRepository
from app.db.session import get_session
from app.services.agent_runner import AgentRunner

router = APIRouter(prefix="/repos", tags=["chat"])


def get_agent_runner() -> AgentRunner:
    """DI seam — overridable in tests with a fake-deps runner."""
    return AgentRunner()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/{repo_id}/chat")
async def chat(
    repo_id: str,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    runner: AgentRunner = Depends(get_agent_runner),
) -> EventSourceResponse:
    repo = await RepoRepository(session).get(repo_id)
    if not repo:
        raise RepoNotFound(f"repo {repo_id} not found")
    if repo.status != "ready":
        raise RepoNotReady(f"repo {repo_id} is '{repo.status}', not ready for questions")

    chat_repo = ChatRepository(session)
    chat_session = (
        await chat_repo.get_session(body.session_id) if body.session_id else None
    ) or await chat_repo.create_session(repo_id)
    await chat_repo.add_message(session_id=chat_session.id, role="user", content=body.message)

    async def gen() -> AsyncIterator[dict]:
        yield {"event": "session", "data": json.dumps({"session_id": chat_session.id})}
        text_parts: list[str] = []
        citations: list[dict] = []
        async for event in runner.stream(repo_id, body.message, repo_name=repo.name):
            if event["type"] == "token":
                text_parts.append(event["text"])
            elif event["type"] == "citations":
                citations = event["citations"]
            yield {"event": event["type"], "data": json.dumps(event)}
        # Persist the assistant turn (uses a fresh session — the request one may be closing).
        from app.db.session import SessionLocal

        async with SessionLocal() as s2:
            await ChatRepository(s2).add_message(
                session_id=chat_session.id,
                role="assistant",
                content="".join(text_parts).strip(),
                citations_json=citations or None,
            )

    return EventSourceResponse(gen())
