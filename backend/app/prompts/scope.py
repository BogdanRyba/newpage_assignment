"""Scope refusal copy — shown when retrieval finds nothing relevant.

Rationale: a documentation assistant must fail honestly. Rather than letting the LLM
improvise when there's no grounding, we short-circuit to a fixed, friendly refusal that
matches the UI's "No matching sources" state. No model call needed.
"""

from __future__ import annotations

VERSION = "scope-v1"


def refusal(repo_name: str | None = None) -> str:
    where = f" in `{repo_name}`" if repo_name else " in this repository"
    return (
        f"I couldn't find anything{where} that answers that. "
        "I can only speak from the indexed code — try asking about a file, function, or "
        "behaviour that exists in the codebase."
    )


INSUFFICIENT_SUPPORT = (
    "I found related code but couldn't ground a confident, citable answer to that question. "
    "Try narrowing it to a specific symbol or file."
)
