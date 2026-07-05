"""Crisis / escalation signal — decide when to hand off to a human or help persona.

Deterministic and cheap: regex over the USER'S QUESTION only (never retrieved code), so an
"escalate now" injected into a source chunk can't trigger a handoff. Patterns require the user
expressing intent (talk to a human, anger, an explicit escalate-this) rather than a bare keyword,
to avoid false positives on questions that merely mention those words. An LLM scorer can refine
this later; the contract — a probability + a threshold gate — stays the same.
"""

from __future__ import annotations

import re

from app.domain.models import Answer

_CRISIS = re.compile(
    r"(talk to (a |an )?(human|person|agent|someone)"
    r"|speak (to|with) (a |an )?(human|person|agent|manager|someone)"
    r"|let me talk to"
    r"|real (human|person)"
    r"|escalate (this|to|me)"
    r"|this is (useless|broken|garbage|terrible|ridiculous|unacceptable)"
    r"|i('m| am) (angry|furious|frustrated|fed up|done)"
    r"|stop wasting"
    r"|file a complaint|i want a refund)",
    re.IGNORECASE,
)


def crisis_probability(question: str) -> float:
    """0..1 likelihood the user is escalating / in distress (1.0 on a confident regex hit)."""
    return 1.0 if _CRISIS.search(question or "") else 0.0


def should_escalate(question: str, *, threshold: float) -> bool:
    return crisis_probability(question) >= threshold


def escalation_answer() -> Answer:
    """A calm, non-cited hand-off message (marked refused=False, this is a deliberate reply)."""
    return Answer(
        text=(
            "It sounds like this is important and you'd like more help. I'm flagging this for a "
            "human on the team to follow up. In the meantime, if you can share the specific file "
            "or behavior you're concerned about, I'll do my best to point you to the exact code."
        ),
        refused=False,
    )
