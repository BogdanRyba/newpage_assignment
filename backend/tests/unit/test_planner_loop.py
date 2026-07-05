"""The gated tool loop: skips when sufficient, runs only what's needed, bounded, injection-safe."""

from __future__ import annotations

from app.domain.models import RepoContext
from app.services.orchestrator.planner_loop import plan_and_execute
from app.services.orchestrator.tools import default_registry
from tests.fakes import make_deps, make_point

CTX = RepoContext(repo_id="r1")


async def test_skips_all_tools_when_planner_says_sufficient() -> None:
    deps = make_deps(points=[], responses=['{"sufficient":true,"actions":[]}'])
    reg = default_registry(deps)
    sources, results = await plan_and_execute(deps, CTX, "trivial question", reg)
    assert reg.calls == []  # no tool invoked
    assert sources == []
    assert results == []


async def test_runs_needed_tool_then_stops() -> None:
    deps = make_deps(
        points=[make_point(path="a.py", symbol="f", text="def f(): ...")],
        responses=[
            '{"sufficient":false,"actions":[{"action":"retrieval","params":{"query":"f"},'
            '"necessity":0.9,"rationale":"need code"}]}',
            '{"sufficient":true,"actions":[]}',
        ],
    )
    reg = default_registry(deps)
    sources, results = await plan_and_execute(deps, CTX, "what is f?", reg)
    assert reg.calls == ["retrieval"]
    assert sources and sources[0].path == "a.py"
    assert sources[0].n == 1  # renumbered


async def test_loop_is_budget_bounded() -> None:
    # Planner is greedy every round; the loop must still terminate within action_budget.
    greedy = (
        '{"sufficient":false,"actions":[{"action":"retrieval",'
        '"params":{"query":"x"},"necessity":0.95}]}'
    )
    deps = make_deps(
        points=[make_point(path="a.py", symbol="f", text="x")],
        responses=[greedy] * 20,  # never declares sufficiency
        action_budget=3,
    )
    reg = default_registry(deps)
    _sources, results = await plan_and_execute(deps, CTX, "x", reg)
    assert len(results) <= 3  # budget caps tool executions


async def test_unknown_action_from_planner_is_ignored() -> None:
    deps = make_deps(
        points=[],
        responses=[
            '{"sufficient":false,"actions":[{"action":"rm_rf","params":{},"necessity":0.99}]}',
            '{"sufficient":true,"actions":[]}',
        ],
    )
    reg = default_registry(deps)
    _sources, results = await plan_and_execute(deps, CTX, "x", reg)
    # The unknown action was attempted but returned ok=False; no crash, no sources.
    assert results and results[0].ok is False
