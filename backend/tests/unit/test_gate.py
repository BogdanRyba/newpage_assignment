"""Confidence gate: the deterministic "% that we need to call it" mechanism.

The LLM only SCORES each candidate action's necessity; this pure gate decides — keep an
action iff its necessity clears the (per-type) threshold, in necessity order, until the budget
is spent. No randomness, fully testable: same scores + thresholds → same survivors.
"""

from __future__ import annotations

from app.services.orchestrator.gate import ProposedAction, gate_actions

_THRESHOLDS = {"retrieval": 0.5, "persona:research": 0.8}


def _a(action: str, necessity: float) -> ProposedAction:
    return ProposedAction(action=action, necessity=necessity)


def test_keeps_actions_at_or_above_threshold() -> None:
    survivors = gate_actions(
        [_a("retrieval", 0.9), _a("graph_neighbors", 0.7)],
        thresholds=_THRESHOLDS, default_threshold=0.6, budget=6,
    )
    assert {s.action for s in survivors} == {"retrieval", "graph_neighbors"}


def test_skips_actions_below_threshold() -> None:
    # retrieval bar is 0.5 (kept); graph_neighbors uses default 0.6 and 0.42 < 0.6 (dropped).
    survivors = gate_actions(
        [_a("retrieval", 0.55), _a("graph_neighbors", 0.42)],
        thresholds=_THRESHOLDS, default_threshold=0.6, budget=6,
    )
    assert [s.action for s in survivors] == ["retrieval"]


def test_nothing_survives_when_all_below_threshold() -> None:
    survivors = gate_actions(
        [_a("authorship_lookup", 0.2), _a("version_diff", 0.1)],
        thresholds=_THRESHOLDS, default_threshold=0.6, budget=6,
    )
    assert survivors == []


def test_per_type_threshold_is_respected() -> None:
    # An expensive persona demands 0.8 — 0.75 isn't enough even though it's "fairly confident".
    survivors = gate_actions(
        [_a("persona:research", 0.75)], thresholds=_THRESHOLDS, default_threshold=0.6, budget=6
    )
    assert survivors == []
    survivors = gate_actions(
        [_a("persona:research", 0.85)], thresholds=_THRESHOLDS, default_threshold=0.6, budget=6
    )
    assert [s.action for s in survivors] == ["persona:research"]


def test_budget_caps_survivors_keeping_the_most_necessary() -> None:
    survivors = gate_actions(
        [_a("retrieval", 0.7), _a("graph_neighbors", 0.95), _a("authorship_lookup", 0.85)],
        thresholds=_THRESHOLDS, default_threshold=0.6, budget=2,
    )
    # Budget=2 → the two highest-necessity survive, in necessity order.
    assert [s.action for s in survivors] == ["graph_neighbors", "authorship_lookup"]
