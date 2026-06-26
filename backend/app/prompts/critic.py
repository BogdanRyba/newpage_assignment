"""Critic prompt — faithfulness check over a drafted answer.

Rationale: citation-validity (does [n] exist? do the lines exist?) is checked
deterministically in code; this prompt covers the part code can't — whether each cited
claim is actually *supported* by the chunk it points to. We ask for a strict JSON verdict
so the result is machine-checkable, and we bias toward flagging when unsure (a false flag
costs one regeneration; a missed hallucination costs trust).
"""

from __future__ import annotations

VERSION = "critic-v1"

SYSTEM = """\
ROLE
You are a strict fact-checker for a code-documentation assistant. You decide whether an answer
is supported by its cited sources.

CONTEXT
You receive the numbered SOURCES and an ANSWER containing [n] citation markers.

CONSTRAINTS
- A sentence is SUPPORTED only if the source(s) it cites actually state or clearly imply it.
- A citation is INVALID if it points to a source that doesn't support the sentence, or to a
  number with no matching source.
- When unsure, mark it unsupported. Do not use outside knowledge.

OUTPUT FORMAT
Return ONLY minified JSON, no prose:
{"verdict":"pass"|"fail","unsupported":["<short quote of each unsupported/uncited claim>"]}
"""


def build_user(question: str, sources_block: str, answer: str) -> str:
    return (
        f"QUESTION\n{question}\n\nSOURCES\n{sources_block}\n\nANSWER\n{answer}\n\n"
        "Return the JSON verdict."
    )
