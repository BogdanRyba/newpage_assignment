"""Orchestrator (Theseus) mode in AgentRunner: crisis escalation, persona selection, merge.

Parallel multi-persona merge is unit-covered in test_merge; here we cover the AgentRunner
composition deterministically (single-persona path + the crisis pre-check + fan-out selection).
"""

from __future__ import annotations

from app.services.agent_runner import AgentRunner
from tests.fakes import make_deps, make_point


def _runner(points, responses):  # noqa: ANN001, ANN202
    deps = make_deps(
        points=points,
        responses=responses,
        orchestrator_enabled=True,
        coordinator_enabled=True,
        dev_search_enabled=True,
    )
    return AgentRunner(deps)


async def test_crisis_question_escalates_to_human() -> None:
    runner = _runner(points=[], responses=[])
    answer = await runner.run("r1", "this is useless, let me talk to a human")
    assert not answer.refused
    assert "human" in answer.text.lower()


def test_persona_selection_fans_out_on_dev_intent() -> None:
    runner = _runner(points=[], responses=[])
    assert runner._select_personas("how does search work?") == ["qa"]
    assert runner._select_personas("who wrote ranking.py?") == ["qa", "dev_search"]


async def test_orchestrated_qa_returns_grounded_answer() -> None:
    # A normal question selects only QA → deterministic single-graph run, then merge of one.
    runner = _runner(
        points=[make_point(path="store.py", symbol="NoteStore", text="class NoteStore: ...")],
        responses=["NoteStore stores notes [1].", '{"verdict":"pass","unsupported":[]}'],
    )
    answer = await runner.run("r1", "what does NoteStore do?")
    assert not answer.refused
    assert answer.citations and answer.citations[0].location.path == "store.py"
