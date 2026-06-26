"""API integration: chat SSE + source serving + not-ready guard.

Real Postgres for repo/file/message rows; the AgentRunner is overridden with fake ports so
no LLM/key is needed. Asserts the SSE event sequence the frontend depends on.
"""

from __future__ import annotations

import json

import httpx
import pytest
from httpx import ASGITransport

from app.api.chat import get_agent_runner
from app.db.repositories.files import FileRepository
from app.db.repositories.repos import RepoRepository
from app.db.session import SessionLocal
from app.main import app
from app.services.agent_runner import AgentRunner
from tests.fakes import make_deps, make_point

pytestmark = pytest.mark.integration

FILE_CONTENT = "class Calculator:\n    def add(self, v):\n        self.total += v\n"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _ready_repo_with_file() -> str:
    async with SessionLocal() as session:
        repo = await RepoRepository(session).create(name="apitest", source_url=None)
        await RepoRepository(session).set_status(repo.id, "ready")
        await FileRepository(session).upsert(
            repo_id=repo.id,
            path="calculator.py",
            lang="python",
            size=len(FILE_CONTENT),
            sha256="x" * 64,
            content=FILE_CONTENT,
        )
    return repo.id


async def test_chat_streams_tokens_then_citations_then_done() -> None:
    repo_id = await _ready_repo_with_file()
    deps = make_deps(
        points=[make_point(path="calculator.py", symbol="add", text=FILE_CONTENT, start=2, end=3)],
        responses=["add increments the running total [1].", '{"verdict":"pass","unsupported":[]}'],
    )
    app.dependency_overrides[get_agent_runner] = lambda: AgentRunner(deps=deps)
    try:
        events: list[str] = []
        payloads: list[dict] = []
        async with await _client() as client:
            async with client.stream(
                "POST", f"/repos/{repo_id}/chat", json={"message": "how does add work?"}
            ) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        events.append(line.split(":", 1)[1].strip())
                    elif line.startswith("data:"):
                        payloads.append(json.loads(line.split(":", 1)[1].strip()))
        assert "token" in events
        assert "citations" in events
        assert events[-1] == "done"
        cite = next(p for p in payloads if p.get("type") == "citations")
        assert cite["citations"][0]["path"] == "calculator.py"
    finally:
        app.dependency_overrides.clear()


async def test_chat_on_unready_repo_returns_409() -> None:
    async with SessionLocal() as session:
        repo = await RepoRepository(session).create(name="pending", source_url="x")
    async with await _client() as client:
        resp = await client.post(f"/repos/{repo.id}/chat", json={"message": "hi"})
    assert resp.status_code == 409


async def test_source_endpoint_returns_numbered_lines() -> None:
    repo_id = await _ready_repo_with_file()
    async with await _client() as client:
        resp = await client.get(
            f"/repos/{repo_id}/source", params={"path": "calculator.py", "start": 2, "end": 3}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["highlight_start"] == 2 and body["highlight_end"] == 3
    assert body["lines"][1]["text"] == "    def add(self, v):"
    assert body["lines"][0]["n"] == 1


async def test_source_missing_file_404() -> None:
    repo_id = await _ready_repo_with_file()
    async with await _client() as client:
        resp = await client.get(f"/repos/{repo_id}/source", params={"path": "nope.py"})
    assert resp.status_code == 404
