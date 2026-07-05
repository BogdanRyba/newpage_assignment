"""The confidence-gated tool loop: plan → gate → execute, bounded by budget.

Each round the planner (LLM) proposes scored actions; the deterministic gate keeps only those
that clear their necessity threshold within the remaining budget; survivors run via the
registry; their results feed the next round's digest. The loop ends when the planner declares
sufficiency, nothing survives the gate, or the budget is spent — so it is structurally finite.
The LLM never executes anything: it only scores, code decides and runs.
"""

from __future__ import annotations

import json
import re

from app.core.logging import get_logger
from app.domain.models import RepoContext
from app.domain.retrieval.context import Source
from app.prompts import planner
from app.services.orchestrator.gate import ProposedAction, gate_actions
from app.services.orchestrator.tools import ToolRegistry, ToolResult
from app.services.query.state import Deps

log = get_logger("planner_loop")
_JSON = re.compile(r"\{.*\}", re.S)


def _parse_plan(raw: str) -> dict:
    m = _JSON.search(raw or "")
    if not m:
        return {"sufficient": True, "actions": []}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {"sufficient": True, "actions": []}
    except (json.JSONDecodeError, ValueError):
        return {"sufficient": True, "actions": []}


def _proposed(plan: dict) -> list[ProposedAction]:
    out: list[ProposedAction] = []
    for a in plan.get("actions", []):
        if not isinstance(a, dict) or "action" not in a:
            continue
        try:
            out.append(ProposedAction(**a))
        except (TypeError, ValueError):
            continue
    return out


async def plan_and_execute(
    deps: Deps, ctx: RepoContext, question: str, registry: ToolRegistry
) -> tuple[list[Source], list[ToolResult]]:
    """Run the gated loop; return (deduped renumbered sources, all tool results)."""
    settings = deps.settings
    actions_block = "\n".join(
        f"- {s.name}: {s.description}" for s in registry.specs_for_prompt()
    )
    tool_results: list[ToolResult] = []
    gathered: list[Source] = []
    seen: set[tuple[str, int, int]] = set()
    budget = settings.action_budget

    for _round in range(settings.action_budget + 1):  # hard backstop on iterations
        if budget <= 0:
            break
        digest = "; ".join(tr.summary for tr in tool_results)
        raw = await deps.generator.complete(
            planner.SYSTEM, planner.build_user(question, actions_block, digest)
        )
        plan = _parse_plan(raw)
        if plan.get("sufficient") and not _proposed(plan):
            break
        survivors = gate_actions(
            _proposed(plan),
            thresholds=settings.gate_thresholds,
            default_threshold=settings.gate_default_threshold,
            budget=budget,
        )
        if not survivors:
            break
        for action in survivors:
            res = await registry.invoke(ctx, action.action, action.params)
            tool_results.append(res)
            budget -= 1
            for s in res.sources:
                key = (s.path, s.start_line, s.end_line)
                if key not in seen:
                    seen.add(key)
                    gathered.append(s)

    # Renumber the deduped union into one [1..M] source list.
    renumbered = [s.model_copy(update={"n": i + 1}) for i, s in enumerate(gathered)]
    return renumbered, tool_results
