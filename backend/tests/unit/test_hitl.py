"""Human-in-the-loop: a high-stakes proposal pauses for approval, then resumes.

Uses an in-memory checkpointer for deterministic pause/resume (durability across processes is
covered by the Postgres integration test). Covers: the run pauses with the proposal as the
interrupt payload; approve finalizes it; reject aborts without applying anything.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

from app.services.agents.hitl import HitlRunner
from tests.fakes import make_deps


def _runner() -> HitlRunner:
    deps = make_deps(points=[], responses=["Refactor ranking.py to inject the Ranker via DI."])
    return HitlRunner(deps, MemorySaver())


async def test_start_pauses_at_approval_with_proposal_payload() -> None:
    out = await _runner().start("t-1", "r1", "improve ranking")
    assert "interrupt" in out
    assert out["interrupt"]["action"] == "apply_change"
    assert "Refactor ranking.py" in out["interrupt"]["proposal"]


async def test_resume_approve_finalizes_the_proposal() -> None:
    runner = _runner()
    await runner.start("t-approve", "r1", "improve ranking")
    out = await runner.resume("t-approve", "approve")
    answer = out["answer"]
    assert not answer.refused
    assert "Refactor ranking.py" in answer.text


async def test_resume_reject_aborts_without_applying() -> None:
    runner = _runner()
    await runner.start("t-reject", "r1", "improve ranking")
    out = await runner.resume("t-reject", "reject")
    answer = out["answer"]
    assert answer.refused
    assert answer.refusal_reason == "rejected"
