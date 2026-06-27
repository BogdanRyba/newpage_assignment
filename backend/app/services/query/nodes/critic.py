"""Critic + terminal nodes — the generator-critic loop's decision point.

The critic combines deterministic citation-validity with an LLM faithfulness verdict, then
either accepts, requests a regeneration (with feedback), drops unsupported sentences, or refuses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from app.core.instrument import instrument
from app.domain.citation.service import build_citations, check_validity, drop_unsupported
from app.domain.models import Answer
from app.prompts import critic as critic_prompt
from app.prompts.scope import INSUFFICIENT_SUPPORT, refusal
from app.services.query.state import Deps, QueryState

Node = Callable[[QueryState], Awaitable[dict]]
_JSON = re.compile(r"\{.*\}", re.S)


def scope_refuse_node(deps: Deps) -> Node:
    @instrument("scope_refuse")
    async def _node(state: QueryState) -> dict:
        text = refusal(state.repo_name)
        return {"answer": Answer(text=text, refused=True, refusal_reason="no_sources")}

    return _node


def critic_node(deps: Deps) -> Node:
    @instrument("critic")
    async def _node(state: QueryState) -> dict:
        # LLM scope gate: the generator emits NO_ANSWER when the sources don't cover the
        # question (off-topic / not in this repo). Convert it to a clean refusal.
        if state.draft.strip().upper().startswith("NO_ANSWER"):
            return {
                "answer": Answer(
                    text=refusal(state.repo_name), refused=True, refusal_reason="no_sources"
                )
            }

        check = check_validity(state.draft, state.sources)
        verdict = await _faithfulness(deps, state)

        if check.is_valid and verdict["pass"]:
            return {"answer": _answer(state.draft, state)}

        # Remember the earliest validly-cited draft — the LLM judge is flaky, so a later
        # regeneration may degrade; we never want to lose a good, citable answer.
        best = state.best_draft or (state.draft if check.is_valid else "")

        if state.critic_iters < deps.settings.max_critic_iterations:
            return {
                "feedback": _feedback(check, verdict),
                "critic_iters": state.critic_iters + 1,
                "best_draft": best,
            }

        # Retries exhausted → keep only supported, cited sentences from the latest draft.
        pruned = drop_unsupported(state.draft, state.sources, verdict["unsupported"])
        if pruned:
            return {"answer": _answer(pruned, state)}
        # Otherwise fall back to a validly-cited draft (latest or earlier) rather than
        # false-refuse over an over-eager judge. Citation-validity is the deterministic, hard
        # guard; an answer with no valid citations at all still refuses.
        fallback = state.draft if check.is_valid else best
        if fallback:
            return {"answer": _answer(fallback, state)}
        return {
            "answer": Answer(
                text=INSUFFICIENT_SUPPORT, refused=True, refusal_reason="insufficient_support"
            )
        }

    return _node


def _answer(text: str, state: QueryState) -> Answer:
    return Answer(text=text, citations=build_citations(text, state.sources))


async def _faithfulness(deps: Deps, state: QueryState) -> dict:
    """Returns {'pass': bool, 'unsupported': [str]}. Conservative on parse failure."""
    raw = await deps.generator.complete(
        critic_prompt.SYSTEM,
        critic_prompt.build_user(state.question, state.sources_block, state.draft),
    )
    match = _JSON.search(raw or "")
    if not match:
        return {"pass": False, "unsupported": []}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"pass": False, "unsupported": []}
    return {
        "pass": data.get("verdict") == "pass",
        "unsupported": [str(x) for x in data.get("unsupported", [])],
    }


def _feedback(check, verdict: dict) -> str:  # noqa: ANN001
    parts: list[str] = []
    if not check.has_any:
        parts.append("The answer has no [n] citations — cite every claim.")
    if check.invalid_markers:
        parts.append(
            f"These citation markers don't exist: {check.invalid_markers}. "
            "Only cite the numbered sources provided."
        )
    for frag in verdict.get("unsupported", []):
        parts.append(f"Unsupported by its source: {frag}")
    return " ".join(parts) or "Some claims were not supported by the cited sources."
