"""Integration: HITL pause survives across runner instances via the Postgres checkpointer.

The whole point of the durable checkpointer (vs in-memory) is that a paused approval can be
resumed by a DIFFERENT process/worker after a restart. We simulate that with two independent
HitlRunner instances (separate saver connections, same Postgres): one starts the run to the
pause, a fresh one resumes it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.agents.hitl import HitlRunner, open_checkpointer
from tests.fakes import make_deps

pytestmark = pytest.mark.integration


async def test_paused_proposal_resumes_from_postgres_in_a_fresh_runner() -> None:
    thread_id = f"hitl-{uuid4().hex}"
    question = "introduce a cache layer"

    # Runner A starts the run and hits the approval pause; its saver connection then closes.
    async with open_checkpointer() as cp_a:
        deps_a = make_deps(points=[], responses=["Add an LRU cache in retrieval/cache.py."])
        started = await HitlRunner(deps_a, cp_a).start(thread_id, "r1", question)
    assert "interrupt" in started
    assert "LRU cache" in started["interrupt"]["proposal"]

    # A brand-new runner (fresh connection, no shared memory) resumes the SAME thread — only
    # possible because the paused state is persisted in Postgres.
    async with open_checkpointer() as cp_b:
        deps_b = make_deps(points=[], responses=["unused"])
        out = await HitlRunner(deps_b, cp_b).resume(thread_id, "approve")

    answer = out["answer"]
    assert not answer.refused
    assert "LRU cache" in answer.text  # the proposal drafted by runner A survived the handoff
