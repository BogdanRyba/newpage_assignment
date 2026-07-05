"""Crisis detection: when to escalate to a human / help persona.

Phase 1 is a cheap deterministic signal (regex over the user's question only — never over
retrieved code, so an injected "escalate now" inside a chunk can't trigger it). Above the
threshold the orchestrator hands off; below, it answers normally.
"""

from __future__ import annotations

from app.services.orchestrator.crisis import crisis_probability, should_escalate


def test_explicit_human_request_scores_high() -> None:
    for q in [
        "this is useless, let me talk to a human",
        "I want to speak to a person",
        "stop wasting my time, I'm furious",
        "escalate this to a manager",
    ]:
        assert crisis_probability(q) >= 0.7, q


def test_normal_questions_score_low() -> None:
    for q in [
        "how does NoteStore search?",
        "who wrote ranking.py?",
        "explain the retrieval pipeline",
    ]:
        assert crisis_probability(q) < 0.7, q


def test_should_escalate_respects_threshold() -> None:
    assert should_escalate("let me talk to a human", threshold=0.7) is True
    assert should_escalate("how does search work?", threshold=0.7) is False


def test_injected_escalation_text_is_not_seen_here() -> None:
    # The scorer only ever receives the user's question. Code/chunk content (where an attacker
    # might write "escalate now") is never passed in — so this benign question stays low.
    assert crisis_probability("describe the function that logs 'escalate now please human'") < 0.7
