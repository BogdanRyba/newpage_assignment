"""Confidence-gated actions — "% that we need to call it", decided deterministically.

The planner (an LLM) proposes candidate actions each with a `necessity` score 0..1; it never
decides whether to act. This pure gate is the decision: sort by necessity, keep each action
that clears its threshold (a per-action override, else the default), stop when the budget is
spent. Auditable and test-stable — the same scores always yield the same survivors, and the
monotonic budget makes the surrounding ReAct loop structurally finite.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProposedAction(BaseModel):
    """One action the planner suggests, with its self-assessed necessity + rationale."""

    action: str  # tool name (e.g. "retrieval") or "persona:<name>"
    params: dict = Field(default_factory=dict)
    necessity: float = 0.0  # 0..1 — how much this action is needed before answering
    rationale: str = ""


def gate_actions(
    proposed: list[ProposedAction],
    *,
    thresholds: dict[str, float],
    default_threshold: float,
    budget: int,
) -> list[ProposedAction]:
    """Keep actions whose necessity clears their threshold, highest first, within budget."""
    survivors: list[ProposedAction] = []
    for action in sorted(proposed, key=lambda a: a.necessity, reverse=True):
        if len(survivors) >= budget:
            break
        if action.necessity >= thresholds.get(action.action, default_threshold):
            survivors.append(action)
    return survivors
