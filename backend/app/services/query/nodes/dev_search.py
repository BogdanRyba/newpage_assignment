"""Dev-search persona nodes: locate the file(s), look up real authorship, answer — grounded.

The grounding guard is deterministic-first: every @author{}/@commit{} the draft asserts must
appear in the looked-up git records, or the draft is rejected and regenerated; at exhaustion we
fall back to a factual answer built straight from the records, so an author absent from git can
never appear in the final answer. Code locations are cited [n] via the shared citation layer.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from app.core.instrument import instrument
from app.domain.citation.service import build_citations
from app.domain.models import Answer, RepoContext
from app.prompts import dev_search
from app.prompts.scope import refusal
from app.services.query.state import Deps, QueryState

Node = Callable[[QueryState], Awaitable[dict]]

_AUTHOR = re.compile(r"@author\{([^}]*)\}")
_COMMIT = re.compile(r"@commit\{([^}]*)\}")
_MAX_TARGETS = 3


def _safe(s: str) -> str:
    """Keep attacker-controlled metadata on one line so it can't break the fenced block."""
    return " ".join((s or "").split())


def locate_targets_node(deps: Deps) -> Node:
    @instrument("locate_targets")
    async def _node(state: QueryState) -> dict:
        seen: list[str] = []
        for hit in state.ranked:
            p = hit.chunk.path
            if p not in seen:
                seen.append(p)
            if len(seen) >= _MAX_TARGETS:
                break
        return {"target_paths": seen}

    return _node


def authorship_lookup_node(deps: Deps) -> Node:
    @instrument("authorship_lookup")
    async def _node(state: QueryState) -> dict:
        if deps.authorship is None or not deps.authorship.enabled:
            return {"authorship": []}
        ctx = RepoContext(repo_id=state.repo_id)
        found = []
        for path in state.target_paths:
            fa = await deps.authorship.file_authorship(ctx, path)
            if fa is not None:
                found.append(fa)
        return {"authorship": found}

    return _node


def assemble_authorship_node(deps: Deps) -> Node:
    @instrument("assemble_authorship")
    async def _node(state: QueryState) -> dict:
        lines = []
        for fa in state.authorship:
            lines.append(
                f"- {fa.path}: last changed by @author{{{_safe(fa.last_author)}}} "
                f"in @commit{{{fa.last_commit_sha[:12]}}} ({_safe(fa.last_commit_at)})"
            )
            for c in fa.recent_commits[:3]:
                lines.append(
                    f"    · @commit{{{c.sha[:12]}}} {_safe(c.author)} — {_safe(c.subject)}"
                )
        return {"authorship_block": "\n".join(lines)}

    return _node


def generate_dev_node(deps: Deps) -> Node:
    @instrument("generate")
    async def _node(state: QueryState) -> dict:
        user = dev_search.build_user(
            state.question, state.authorship_block, state.sources_block,
            feedback=state.feedback or None,
        )
        draft = await deps.generator.complete(dev_search.SYSTEM, user)
        return {"draft": draft.strip()}

    return _node


def grounding_check_node(deps: Deps) -> Node:
    """Validate attributions against real git records; retry, else fall back to facts."""

    @instrument("grounding_check")
    async def _node(state: QueryState) -> dict:
        draft = state.draft
        if draft.strip() == "NO_ANSWER":
            return _refuse(state, "authorship_unavailable")

        real_authors = _real_authors(state)
        real_commits = _real_commits(state)
        bad_authors = [a for a in _AUTHOR.findall(draft) if _norm(a) not in real_authors]
        bad_commits = [c for c in _COMMIT.findall(draft) if c[:12] not in real_commits]

        max_iters = deps.settings.max_critic_iterations
        if (bad_authors or bad_commits) and state.critic_iters < max_iters:
            issues = ", ".join(bad_authors + bad_commits)
            return {
                "feedback": f"Not in the git records: {issues}.",
                "critic_iters": state.critic_iters + 1,
            }

        # Valid, or budget exhausted → emit a grounded answer.
        if bad_authors or bad_commits:
            text = _factual_fallback(state)  # deterministic: only real records
        else:
            text = _strip_markers(draft)
        citations = build_citations(text, state.sources)
        return {"answer": Answer(text=text, citations=citations)}

    return _node


def authorship_refuse_node(deps: Deps) -> Node:
    @instrument("authorship_refuse")
    async def _node(state: QueryState) -> dict:
        return _refuse(state, "authorship_unavailable")

    return _node


def _refuse(state: QueryState, reason: str) -> dict:
    msg = (
        "I don't have authorship history for the file(s) this question points at, so I can't say "
        "who wrote it."
    )
    if not state.authorship:
        return {"answer": Answer(text=msg, refused=True, refusal_reason=reason)}
    return {
        "answer": Answer(
            text=refusal(state.repo_name or "this repo"), refused=True, refusal_reason=reason
        )
    }


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def _real_authors(state: QueryState) -> set[str]:
    out: set[str] = set()
    for fa in state.authorship:
        out.add(_norm(fa.last_author))
        for c in fa.recent_commits:
            out.add(_norm(c.author))
    return out


def _real_commits(state: QueryState) -> set[str]:
    out: set[str] = set()
    for fa in state.authorship:
        if fa.last_commit_sha:
            out.add(fa.last_commit_sha[:12])
        for c in fa.recent_commits:
            out.add(c.sha[:12])
    return out


def _strip_markers(text: str) -> str:
    text = _AUTHOR.sub(lambda m: m.group(1), text)
    return _COMMIT.sub(lambda m: m.group(1)[:8], text)


def _factual_fallback(state: QueryState) -> str:
    """Answer built only from real records — used when the LLM named someone not in git."""
    parts = []
    for i, fa in enumerate(state.authorship, start=1):
        when = f" on {fa.last_commit_at[:10]}" if fa.last_commit_at else ""
        commit = f" ({fa.last_commit_sha[:8]})" if fa.last_commit_sha else ""
        cite = f" [{i}]" if i <= len(state.sources) else ""
        parts.append(f"{fa.path} was last changed by {fa.last_author}{when}{commit}.{cite}")
    return " ".join(parts)
