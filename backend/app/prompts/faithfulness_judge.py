"""Faithfulness judge prompt — used by the eval-runner (LLM-as-judge), not the live path.

Rationale: separates *offline quality measurement* from the *live critic*. The live critic
gates a single answer; this judge scores a whole golden set so CI can fail on regressions.
Kept as its own versioned artifact so a judge-prompt change is traceable in eval history.
"""

from __future__ import annotations

VERSION = "faithfulness-judge-v1"

SYSTEM = """\
ROLE
You grade how faithful a code-documentation answer is to its sources, for offline evaluation.

CONTEXT
You receive SOURCES and an ANSWER with [n] markers.

CONSTRAINTS
- Score 1.0 only if every claim is supported by a cited source.
- Penalise unsupported claims, wrong citations, and outside knowledge.
- Judge only against the sources provided.

OUTPUT FORMAT
Return ONLY minified JSON: {"faithfulness": <float 0..1>, "reason": "<one sentence>"}
"""


def build_user(question: str, sources_block: str, answer: str) -> str:
    return (
        f"QUESTION\n{question}\n\nSOURCES\n{sources_block}\n\nANSWER\n{answer}\n\nReturn the JSON."
    )
