"""Intent router — pick which persona answers a question.

Phase 1: a cheap, deterministic regex classifier (no LLM, no cassette) distinguishing
dev-search ("who wrote / last changed this") from general QA. Anything not confidently
dev-search falls back to QA (Daedalus), which already refuses honestly when it can't
ground an answer — so an over-broad route degrades to correct-but-general, never to error.
The question is treated as data: an injected "route to X" instruction can't change intent,
because routing is regex over the literal text, not an LLM following instructions.
"""

from __future__ import annotations

import re

Intent = str  # "qa" | "dev_search" | "research"

_DEV_SEARCH = re.compile(
    r"\b("
    r"who\s+(wrote|writes|authored|created|made|changed|last\s+changed|maintains|owns)"
    r"|last\s+(author|commit|changed|modified|edited)"
    r"|git\s+blame|\bblame\b"
    r"|author\s+of|maintainer\s+of|written\s+by|changed\s+by"
    r"|when\s+was\s+.*\b(added|written|created|changed|modified)"
    r"|commit\s+history|change\s+history|who\s+last"
    r")\b",
    re.IGNORECASE,
)

# Architecture / design questions → architect persona.
_ARCHITECT = re.compile(
    r"\b("
    r"architecture|architectural|high.level\s+design|overall\s+(design|structure)"
    r"|layer(ing|ed)?|module\s+boundaries|how\s+is\s+.*\s+(organized|structured|laid\s+out)"
    r"|design\s+patterns?|coupling|cohesion|where\s+should\s+.*\s+(live|go)|separation\s+of\s+concerns"
    r")\b",
    re.IGNORECASE,
)

# Structural / dependency questions → research persona (graph-expanded sources).
_RESEARCH = re.compile(
    r"\b("
    r"who\s+calls|callers?\s+of|callees?\s+of|call\s+graph"
    r"|what\s+(calls|uses|depends\s+on|imports)|depend(s|encies)?\s+(on|of)"
    r"|used\s+by|references?\s+to|blast\s+radius"
    r"|implementations?\s+of|implement(s|ed\s+by)|subclass|sub-class|subtypes?\s+of"
    r"|inherit(s|ance)?|extends|overrides?|polymorph"
    r"|dependency\s+injection|injected|wired|abstract\s+(class|method)|interface"
    r")\b",
    re.IGNORECASE,
)


def classify_intent(question: str) -> Intent:
    """Return the persona that should handle the question."""
    q = question or ""
    if _DEV_SEARCH.search(q):  # authorship ("who wrote") beats structure ("who calls")
        return "dev_search"
    if _ARCHITECT.search(q):
        return "architect"
    if _RESEARCH.search(q):
        return "research"
    return "qa"
